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
"""Utils of docker interaction"""

import io
import json
import os
import re
import socket
import string
import tarfile
import warnings
from contextlib import contextmanager, suppress
from dataclasses import asdict, dataclass
from gzip import compress
from typing import Optional, Tuple

import allure
import docker
import pytest
import requests.exceptions
from adcm_client.objects import ADCMClient
from adcm_client.util.wait import wait_for_url
from allure_commons.types import AttachmentType
from coreapi.exceptions import ErrorMessage
from docker import DockerClient
from docker.errors import APIError, ImageNotFound, NotFound
from docker.models.containers import Container
from docker.utils import parse_repository_tag
from retry.api import retry_call

from .utils import random_string
from .common import add_dummy_objects_to_adcm

MIN_DOCKER_PORT = 8000
MAX_DOCKER_PORT = 9000
DEFAULT_IP = "127.0.0.1"
CONTAINER_START_RETRY_COUNT = 20
MAX_WORKER_COUNT = 80


class UnableToBind(Exception):
    """Raise when no free port to expose on docker container"""


class RetryCountExceeded(Exception):
    """Raise when container restart count is exceeded"""


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
        with open(path, encoding="utf-8") as file:
            for line in file:
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


# pylint: disable=too-many-instance-attributes,invalid-name
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
            image = {"repo": self.repo, "tag": self.tag}
        else:
            image = self.init_adcm()
        return image

    def init_adcm(self):
        """Init ADCM coinaiter and commit it into image"""
        dw = DockerWrapper(dc=self.dc)
        config = ContainerConfig(image=self.adcm_repo, tag=self.adcm_tag, remove=False, pull=self.pull)
        self._adcm = ADCM(docker_wrapper=dw, container_config=config)
        # Pre-upload bundles to ADCM before image initialization
        self._preupload_bundles()
        # Fill ADCM with a dummy objects
        self._fill_dummy_data()
        # Create a snapshot from initialized container
        self._adcm.stop()
        with allure.step(f"Commit initialized ADCM container to image {self.repo}:{self.tag}"):
            self._adcm.container.commit(repository=self.repo, tag=self.tag)
        self._adcm.remove()
        return {"repo": self.repo, "tag": self.tag}

    def _preupload_bundles(self):
        """Pre-upload bundles to ADCM image"""
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


def image_exists(repo: str, tag: str, dc: Optional[DockerClient] = None):
    """
    Check if docker image exists in the given DockerClient
    If no DockerClient passed use one from env
    """
    if dc is None:
        dc = docker.from_env(timeout=120)
    try:
        dc.images.get(name=f"{repo}:{tag}")
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
    >>> split_tag('fedora/httpd@sha256:12345')
    ('fedora/httpd', 'sha256:12345')
    """
    warnings.warn("Please use parse_repository_tag from docker.utils", DeprecationWarning)
    return parse_repository_tag(image_name)


def _wait_for_adcm_container_init(container, container_ip, port, timeout=120):
    adcm_api_url = f"http://{container_ip}:{port}/api/v1/"
    with allure.step(f"Waiting for ADCM API on {adcm_api_url}"):
        if not wait_for_url(adcm_api_url, timeout):
            additional_message = ""
            try:
                container.kill()
            except APIError:
                additional_message = " \nWARNING: Failed to kill docker container. Try to remove it by hand"
            raise TimeoutError(f"ADCM API has not responded in {timeout} seconds{additional_message}")


@dataclass
class ContainerConfig:
    """Dataclass for encapsulating docker container run options"""

    image: Optional[str] = None
    tag: Optional[str] = None
    pull: bool = True
    remove: bool = True
    labels: Optional[dict] = None
    bind_ip: Optional[str] = None
    bind_port: Optional[int] = None
    api_ip: Optional[str] = None
    api_port: Optional[int] = None
    volumes: Optional[dict] = None
    name: Optional[str] = None
    docker_url: Optional[str] = None

    def __post_init__(self):
        """Default values for some fields overwritten by None,
        therefore we have to init them with expected defaults."""
        self.image = self.image or "hub.arenadata.io/adcm/adcm"
        self.tag = self.tag or "latest"
        self.bind_ip = self.bind_ip or DEFAULT_IP
        self.labels = self.labels or {}

    @property
    def full_image(self) -> str:
        """Join image and tag"""
        if not self.tag:
            full_image = self.image
        elif self.tag.startswith("sha256:"):
            full_image = f"{self.image}@{self.tag}"
        else:
            full_image = f"{self.image}:{self.tag}"
        return full_image


class DockerWrapper:  # pylint: disable=too-few-public-methods
    """Class for connection to local docker daemon and spawn ADCM instances."""

    __slots__ = ("client",)

    def __init__(self, base_url="unix://var/run/docker.sock", dc=None):
        self.client = dc if dc else docker.DockerClient(base_url=base_url, timeout=120)

    def run_adcm_container_from_config(self, config: ContainerConfig) -> Tuple[Container, ContainerConfig]:
        """
        Run ADCM container from the docker image.
        Return ADCM container and updated container config.
        """
        if config.pull:
            self.client.images.pull(config.image, config.tag)
        if os.environ.get("BUILD_TAG"):
            config.labels.update({"jenkins-job": os.environ["BUILD_TAG"]})

        # Check if we use remote dockerd
        if "localhost" not in self.client.api.base_url:
            # dc.api.base_url is most likely tcp://{cmd_opts.remote_docker}
            base_url = self.client.api.base_url
            ip_start = base_url.rfind("/") + 1
            ip_end = base_url.rfind(":")
            config.bind_ip = base_url[ip_start:ip_end]

        with allure.step(f"Run ADCM container from {config.image}:{config.tag}"):
            allure.attach(
                json.dumps(asdict(config), indent=2),  # config object is not serializable
                name="Container config",
                attachment_type=AttachmentType.JSON,
            )
            container, config.bind_port = (
                self._run_container(config) if config.bind_port else self._run_container_on_free_port(config)
            )

        config.api_ip, config.api_port = self._get_adcm_ip_and_port(config, container)

        _wait_for_adcm_container_init(container, config.api_ip, config.api_port)

        return container, config

    def _run_container_on_free_port(self, config: ContainerConfig) -> Tuple[Container, int]:
        config.bind_port = _find_port(config.bind_ip)
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
                    config.bind_port = _find_port(config.bind_ip, config.bind_port + 1)
                else:
                    raise err
        raise RetryCountExceeded(f"Unable to start container after {CONTAINER_START_RETRY_COUNT} retries")

    def _run_container(self, config: ContainerConfig) -> Container:
        return (
            self.client.containers.run(
                config.full_image,
                ports={"8000": (config.bind_ip, config.bind_port)},
                volumes=config.volumes,
                remove=config.remove,
                labels=config.labels,
                name=config.name,
                detach=True,
            ),
            config.bind_port,
        )

    def _get_adcm_ip_and_port(self, config: ContainerConfig, container) -> Tuple[str, str]:
        # If test runner is running in docker then 127.0.0.1
        # will be local container loop interface instead of host loop interface,
        # so we need to establish ADCM API connection using internal docker network
        api_ip, api_port = config.bind_ip, config.bind_port
        if config.bind_ip == DEFAULT_IP and is_docker():
            api_ip = self.client.api.inspect_container(container.id)["NetworkSettings"]["IPAddress"]
            api_port = "8000"
        return api_ip, api_port


class ADCM:
    """
    Class that incorporates basic ADCM stuff namely:
    - Docker container
    - API URL
    - ADCM upgrade feature
    """

    __slots__ = ("container", "container_config", "docker_wrapper")

    def __init__(self, docker_wrapper: DockerWrapper, container_config: ContainerConfig):
        self.docker_wrapper = docker_wrapper
        self.container_config = container_config
        # run ADCM container
        self.container, self.container_config = self.docker_wrapper.run_adcm_container_from_config(
            self.container_config
        )

    @property
    def url(self):
        """ADCM base URL"""
        return f"http://{self.ip}:{self.port}"

    @property
    def ip(self):
        """ADCM IP address"""
        return self.container_config.api_ip

    @property
    def port(self):
        """ADCM IP address"""
        return self.container_config.api_port

    @allure.step("Stop ADCM container")
    def stop(self):
        """Stop ADCM container"""
        self.container.stop()
        if self.container_config.remove:
            with suppress(NotFound):
                condition = "removed" if self.container.attrs["HostConfig"]["AutoRemove"] else "stopped"
                with suppress_docker_wait_error():
                    self.container.wait(condition=condition, timeout=30)

    @allure.step("Remove ADCM container")
    def remove(self):
        """Remove ADCM container"""
        with suppress(NotFound):
            self.container.remove()

    @allure.step("Upgrade ADCM to {target}")
    def upgrade(self, target: Tuple[str, str]) -> None:
        """Stop old ADCM container and start new container with /adcm/data mounted"""
        image, tag = target
        assert (
            self.container_config.volumes
        ), "There is no volume to move data. Make sure you are using the correct ADCM fixture for upgrade"
        volume_name = list(self.container_config.volumes.keys()).pop()
        volume = self.container_config.volumes.get(volume_name)
        with allure.step("Copy /adcm/data to the folder attached by volume"):
            self.container.exec_run(f"sh -c 'cp -a /adcm/data/* {volume['bind']}'")
        with allure.step("Update ADCM container config"):
            self.container_config.image = image
            self.container_config.tag = tag
            volume.update({"bind": "/adcm/data"})
        with allure.step("Stop old ADCM container"):
            self.stop()
        with allure.step("Start newer ADCM container"):
            self.container, self.container_config = self.docker_wrapper.run_adcm_container_from_config(
                self.container_config
            )


def remove_docker_image(repo: str, tag: str, dc: DockerClient):
    """Remove docker image"""
    image_name = f"{repo}:{tag}"
    for container in dc.containers.list(filters=dict(ancestor=image_name)):
        with suppress_docker_wait_error():
            container.wait(condition="removed", timeout=30)
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


@contextmanager
def suppress_docker_wait_error():
    """
    Suppress requests ConnectionError to avoid unhandled docker-py exception
    """
    try:
        yield
    except requests.exceptions.ConnectionError:
        warnings.warn(
            "Failed to wait container state at the specified timeout\n"
            "It's workaround of docker-py error, see https://github.com/docker/docker-py/issues/1966"
        )
