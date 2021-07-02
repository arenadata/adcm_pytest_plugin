# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# pylint: disable=redefined-outer-name, C0103, E0401
import io
import json
import os
import re
import socket
import string
import tarfile
from contextlib import contextmanager, suppress
from dataclasses import asdict, dataclass
from gzip import compress
from typing import Optional, Tuple

import allure
import docker
import pytest
from adcm_client.objects import ADCMClient
from adcm_client.util.wait import wait_for_url
from adcm_client.wrappers.api import ADCMApiWrapper
from allure_commons.types import AttachmentType
from coreapi.exceptions import ErrorMessage
from deprecated import deprecated
from docker import DockerClient
from docker.errors import APIError, ImageNotFound, NotFound
from docker.models.containers import Container
from retry.api import retry_call

from .utils import random_string
from .common import add_dummy_objects_to_adcm

MIN_DOCKER_PORT = 8000
MAX_DOCKER_PORT = 9000
DEFAULT_IP = "127.0.0.1"
CONTAINER_START_RETRY_COUNT = 20
MAX_WORKER_COUNT = 80


class UnableToBind(Exception):
    pass


class RetryCountExceeded(Exception):
    pass


def _port_is_free(ip, port) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        return sock.connect_ex((ip, port)) != 0


def _find_port(ip, port_from: int = 0) -> int:
    gw_count = os.environ.get("PYTEST_XDIST_WORKER_COUNT", 0)
    if int(gw_count) > MAX_WORKER_COUNT:
        pytest.exit("Expected maximum workers count is {MAX_WORKER_COUNT}.")
    gw_name = os.environ.get("PYTEST_XDIST_WORKER", "gw0")
    gw_number = int(gw_name.strip(string.ascii_letters))
    range_length = (MAX_DOCKER_PORT - MIN_DOCKER_PORT) // MAX_WORKER_COUNT
    offset = MIN_DOCKER_PORT + gw_number * range_length
    range_start = max(port_from, offset)
    for port in range(range_start, range_start + range_length):
        if _port_is_free(ip, port):
            return port
    raise UnableToBind("There is no free port for the given worker.")


def is_docker() -> bool:
    """
    Look into cgroup to detect if we are in container
    """
    path = "/proc/self/cgroup"
    try:
        with open(path) as f:
            for line in f:
                if re.match(r"\d+:[\w=]+:/docker(-[ce]e)?/\w+", line):
                    return True
    except FileNotFoundError:
        pass
    return False


@contextmanager
def gather_adcm_data_from_container(adcm: "ADCM"):
    """
    Get /adcm/data/ form ADCM docker container
    :return: compressed file stream
    """
    bits, _ = adcm.container.get_archive("/adcm/data/")

    with io.BytesIO() as stream:
        for chunk in bits:
            stream.write(chunk)
        stream.seek(0)
        yield compress(stream.getvalue())


def get_file_from_container(instance, path, filename):
    """
    Get file from docker container and return file object

    Args:
        instance: ADCM instance
        path (str): path to file in container
        filename (str): filename in path

    Returns:
        (file object): The extracted file from tar archive from docker container

    """

    stream = instance.container.get_archive(path + filename)[0]
    file_obj = io.BytesIO()
    for i in stream:
        file_obj.write(i)
    file_obj.seek(0)
    with tarfile.open(mode="r", fileobj=file_obj) as tar:
        return tar.extractfile(filename)


@deprecated
def get_initialized_adcm_image(
    repo="local/adcminit",
    tag=None,
    adcm_repo=None,
    adcm_tag=None,
    pull=True,
    dc=None,
) -> dict:
    """
    Wrapper for backward capability
    """
    return ADCMInitializer(
        repo=repo,
        tag=tag,
        adcm_repo=adcm_repo,
        adcm_tag=adcm_tag,
        pull=pull,
        dc=dc,
    ).get_initialized_adcm_image()


# pylint: disable=too-many-instance-attributes
class ADCMInitializer:
    """
    Class for initialized ADCM image preparation.
    """

    __slots__ = (
        "repo",
        "tag",
        "adcm_repo",
        "adcm_tag",
        "pull",
        "dc",
        "preupload_bundle_urls",
        "adcm_api_credentials",
        "fill_dummy_data",
        "_adcm",
        "_adcm_cli",
    )

    # pylint: disable=too-many-arguments
    def __init__(
        self,
        repo="local/adcminit",
        tag=None,
        adcm_repo=None,
        adcm_tag=None,
        pull=True,
        dc=None,
        preupload_bundle_urls=None,
        adcm_api_credentials=None,
        fill_dummy_data=False,
    ):
        self.repo = repo
        self.tag = tag if tag else random_string()
        self.adcm_repo = adcm_repo
        self.adcm_tag = adcm_tag
        self.pull = pull
        self.dc = dc if dc else docker.from_env(timeout=120)
        self.preupload_bundle_urls = preupload_bundle_urls
        self.adcm_api_credentials = adcm_api_credentials if adcm_api_credentials else {}
        self.fill_dummy_data = fill_dummy_data
        self._adcm = None
        self._adcm_cli = None

    @allure.step("Prepare initialized ADCM image")
    def get_initialized_adcm_image(self) -> dict:
        """
        If image with given 'repo' and 'tag' then it was most likely created with staticimage run,
        so we just use it.
        If there is no image with given 'repo' and 'tag' we will create a new one
        """

        if image_exists(self.repo, self.tag, self.dc):
            return {"repo": self.repo, "tag": self.tag}
        else:
            return self.init_adcm()

    def init_adcm(self):
        dw = DockerWrapper(dc=self.dc)
        config = ContainerConfig(image=self.adcm_repo, tag=self.adcm_tag, remove=False, pull=self.pull)
        # Check if we use remote dockerd
        if self.dc and "localhost" not in self.dc.api.base_url:
            # dc.api.base_url is most likely tcp://{cmd_opts.remote_docker}
            base_url = self.dc.api.base_url
            ip_start = base_url.rfind("/") + 1
            ip_end = base_url.rfind(":")
            config.ip = base_url[ip_start:ip_end]
        self._adcm = dw.run_adcm_from_config(config)
        # Pre-upload bundles to ADCM before image initialization
        self._preupload_bundles()
        # Fill ADCM with a dummy objects
        self._fill_dummy_data()
        # Create a snapshot from initialized container
        self._adcm.container.stop()
        with allure.step(f"Commit initialized ADCM container to image {self.repo}:{self.tag}"):
            self._adcm.container.commit(repository=self.repo, tag=self.tag)
        self._adcm.container.remove()
        return {"repo": self.repo, "tag": self.tag}

    def _preupload_bundles(self):
        if self.preupload_bundle_urls:
            with allure.step("Pre-upload bundles into ADCM before image initialization"):
                self._init_adcm_cli()
                for url in self.preupload_bundle_urls:
                    retry_call(
                        self._upload_bundle,
                        fargs=[url],
                        tries=5,
                    )

    def _fill_dummy_data(self):
        if self.fill_dummy_data:
            self._init_adcm_cli()
            add_dummy_objects_to_adcm(self._adcm_cli)

    def _upload_bundle(self, url):
        try:
            self._adcm_cli.upload_from_url(url)
        except ErrorMessage as exception:
            # skip error only if bundle was already uploaded before
            # can occur in case of --staticimage use
            if "BUNDLE_ERROR" not in exception.error:
                raise exception

    def _init_adcm_cli(self):
        if not self._adcm_cli:
            self._adcm_cli = ADCMClient(url=self._adcm.url, **self.adcm_api_credentials)


def image_exists(repo, tag, dc=None):
    if dc is None:
        dc = docker.from_env(timeout=120)
    try:
        dc.images.get(name="{}:{}".format(repo, tag))
    except ImageNotFound:
        return False
    return True


def split_tag(image_name: str):
    """
    Split docker image name

    >>> split_tag('fedora/httpd')
    ('fedora/httpd', None)
    >>> split_tag('fedora/httpd:')
    ('fedora/httpd', '')
    >>> split_tag('fedora/httpd:version1.0')
    ('fedora/httpd', 'version1.0')
    """
    image = image_name.split(":")
    if len(image) > 1:
        image_repo = image[0]
        image_tag = image[1]
    else:
        image_repo = image[0]
        image_tag = None
    return image_repo, image_tag


def _wait_for_adcm_container_init(container, container_ip, port, timeout=120):
    if not wait_for_url(f"http://{container_ip}:{port}/api/v1/", timeout):
        additional_message = ""
        try:
            container.kill()
        except APIError:
            additional_message = " \nWARNING: Failed to kill docker container. Try to remove it by hand"
        raise TimeoutError(f"ADCM API has not responded in {timeout} seconds{additional_message}")


@dataclass
class ContainerConfig:
    """Dataclass for incapsulating docker container run options"""

    image: Optional[str] = None
    tag: Optional[str] = None
    pull: bool = True
    remove: bool = True
    labels: Optional[dict] = None
    ip: Optional[str] = None
    port: Optional[int] = None
    volumes: Optional[dict] = None
    name: Optional[str] = None
    docker_url: Optional[str] = None

    def __post_init__(self):
        """Default values for some fields overwritten by None,
        therefore we have to init them with expected defaults."""
        self.image = self.image or "hub.arenadata.io/adcm/adcm"
        self.tag = self.tag or "latest"
        self.ip = self.ip or DEFAULT_IP
        self.labels = self.labels or {}


class ADCM:
    """
    Class that wraps ADCM Api operation over self.api (ADCMApiWrapper)
    and wraps docker over self.container (see docker module for info)
    """

    __slots__ = ("container", "container_config", "ip", "port", "url", "api")

    def __init__(self, container: Container, ip: str, port: str, container_config: Optional[ContainerConfig]):
        self.container = container
        self.container_config = container_config
        self.ip = ip
        self.port = port
        self.url = "http://{}:{}".format(self.ip, self.port)
        self.api = ADCMApiWrapper(self.url)

    def stop(self):
        """Stops container"""
        self.container.stop()
        with suppress(NotFound):
            condition = "removed" if self.container.attrs["HostConfig"]["AutoRemove"] else "stopped"
            self.container.wait(condition=condition, timeout=30)

    @allure.step("Upgrade adcm to {target}")
    def upgrade(self, target: Tuple[str, str]) -> None:
        image, tag = target
        assert (
            self.container_config.volumes
        ), "There is no volume to move data. Make sure you are using the correct ADCM fixture for upgrade"
        volume_name = list(self.container_config.volumes.keys()).pop()
        volume = self.container_config.volumes.get(volume_name)
        with allure.step("Copy /adcm/data to folder attached by volume"):
            self.container.exec_run(f"sh -c 'cp -a /adcm/data/* {volume['bind']}'")
        with allure.step("Update container config"):
            self.container_config.image = image
            self.container_config.tag = tag
            volume.update({"bind": "/adcm/data"})
            allure.attach(
                json.dumps(asdict(self.container_config), indent=2),  # config object is not serializable
                name="Container config for upgrade",
                attachment_type=AttachmentType.JSON,
            )
        with allure.step("Stop old container"):
            self.stop()
        with allure.step("Start newer adcm"):
            dw = DockerWrapper(base_url=self.container_config.docker_url)
            container, _ = dw.adcm_container_from_config(self.container_config)
            _wait_for_adcm_container_init(container, self.ip, self.port, timeout=30)
            self.container = container


class DockerWrapper:
    """Class for connection to local docker daemon and spawn ADCM instances."""

    __slots__ = ("client",)

    def __init__(self, base_url="unix://var/run/docker.sock", dc=None):
        self.client = dc if dc else docker.DockerClient(base_url=base_url, timeout=120)

    # pylint: disable=too-many-arguments
    @deprecated(reason="use run_adcm_from_config method")
    def run_adcm(
        self,
        image=None,
        labels=None,
        remove=True,
        pull=True,
        name=None,
        tag=None,
        ip=None,
        volumes=None,
    ):
        """
        Run ADCM in docker image.
        Return ADCM instance.

        Example:
        adcm = docker.run(image='arenadata/adcm', tag=None, ip='127.0.0.1')

        If tag is None or is not present than a tag 'latest' will be used
        """
        config = ContainerConfig(
            image=image,  # keep from black
            labels=labels,
            remove=remove,
            pull=pull,
            name=name,
            tag=tag,
            ip=ip,
            volumes=volumes,
        )
        return self.run_adcm_from_config(config)

    def run_adcm_from_config(self, config: ContainerConfig):
        """
        Run ADCM in docker image.
        Return ADCM instance.

        Example:
        adcm = docker.run(image='arenadata/adcm', tag=None, ip='127.0.0.1')

        If tag is None or is not present than a tag 'latest' will be used
        """
        if config.pull:
            self.client.images.pull(config.image, config.tag)
        if os.environ.get("BUILD_TAG"):
            config.labels.update({"jenkins-job": os.environ["BUILD_TAG"]})

        container, port = self.adcm_container_from_config(config)

        # If test runner is running in docker then 127.0.0.1
        # will be local container loop interface instead of host loop interface,
        # so we need to establish ADCM API connection using internal docker network
        if config.ip == DEFAULT_IP and is_docker():
            config.ip = self.client.api.inspect_container(container.id)["NetworkSettings"]["IPAddress"]
            port = "8000"
        _wait_for_adcm_container_init(container, config.ip, port)
        return ADCM(container, config.ip, port, container_config=config)

    # pylint: disable=too-many-arguments
    @deprecated(reason="use adcm_container_from_config")
    def adcm_container(
        self,
        image=None,
        labels=None,
        remove=True,
        name=None,
        tag=None,
        ip=None,
        volumes=None,
    ):
        config = ContainerConfig(
            image=image,  # keep from black
            labels=labels,
            remove=remove,
            name=name,
            tag=tag,
            ip=ip,
            volumes=volumes,
        )
        return self.adcm_container_from_config(config)

    def adcm_container_from_config(self, config: ContainerConfig):
        """
        Run ADCM in docker image.
        Return ADCM container and bind port.
        """
        with allure.step(f"Run ADCM container from {config.image}:{config.tag}"):
            allure.attach(
                json.dumps(asdict(config), indent=2),  # config object is not serializable
                name="Container config",
                attachment_type=AttachmentType.JSON,
            )
            container = self._run_container(config) if config.port else self._run_container_on_free_port(config)
        with allure.step(f"ADCM API started on {config.ip}:{config.port}/api/v1"):
            return container, config.port

    def _run_container_on_free_port(self, config: ContainerConfig) -> Container:
        config.port = _find_port(config.ip)
        for _ in range(0, CONTAINER_START_RETRY_COUNT):
            try:
                return self._run_container(config)
            except APIError as err:
                if (
                    "failed: port is already allocated" in err.explanation
                    or "bind: address already in use" in err.explanation  # noqa: W503
                ):
                    # such error excepting leaves created container and there is
                    # no way to clean it other than from docker library
                    # try to find next one port
                    config.port = _find_port(config.ip, config.port + 1)
                else:
                    raise err
        raise RetryCountExceeded(f"Unable to start container after {CONTAINER_START_RETRY_COUNT} retries")

    def _run_container(self, config: ContainerConfig) -> Container:
        return self.client.containers.run(
            "{}:{}".format(config.image, config.tag),
            ports={"8000": (config.ip, config.port)},
            volumes=config.volumes,
            remove=config.remove,
            labels=config.labels,
            name=config.name,
            detach=True,
        )


def remove_docker_image(repo: str, tag: str, dc: DockerClient):
    """Remove docker image"""
    image_name = f"{repo}:{tag}"
    for container in dc.containers.list(filters=dict(ancestor=image_name)):
        try:
            container.wait(condition="removed", timeout=30)
        except ConnectionError:
            # https://github.com/docker/docker-py/issues/1966 workaround
            pass
    retry_call(
        dc.images.remove,
        fargs=[image_name],
        fkwargs={"force": True},
        tries=5,
    )


def remove_container_volumes(container: Container, dc: DockerClient):
    """Remove volumes related to the given container.
    Note that container should be removed before function call."""
    for name in [mount["Name"] for mount in container.attrs["Mounts"] if mount["Type"] == "volume"]:
        with suppress(NotFound):  # volume may be removed already
            dc.volumes.get(name).remove()
