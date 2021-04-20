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

import time
from typing import Optional

import allure
import docker
import ifaddr
import pytest
import socket

from adcm_client.base import Paging, WaitTimeout
from adcm_client.objects import ADCMClient
from allure_commons.reporter import AllureReporter
from allure_commons.utils import uuid4
from allure_pytest.listener import AllureListener
from requests.exceptions import ReadTimeout as DockerReadTimeout
from retry.api import retry_call
from deprecated import deprecated

from .docker_utils import (
    ADCM,
    DockerWrapper,
    is_docker,
    gather_adcm_data_from_container,
    get_initialized_adcm_image,
    split_tag,
)
from .utils import check_mutually_exclusive, remove_host

__all__ = [
    "image",
    "cmd_opts",
    "adcm",
    "client",
    "adcm_fs",
    "adcm_ss",
    "adcm_ms",
    "sdk_client_ms",
    "sdk_client_fs",
    "sdk_client_ss",
]


# pylint: disable=W0621
@allure.title("ADCM Image")
@pytest.fixture(scope="session")
def image(request, cmd_opts):
    """That fixture creates ADCM container, waits until
    a database becomes initialised and stores that as images
    with random tag and name local/adcminit

    That can be useful to use that fixture to make ADCM's
    container startup time shorter.

    Operates with cmd-opts:
     '--staticimage INIT_IMAGE'
     '--adcm-image IMAGE'
     '--remote-docker HOST:PORT'
     '--dontstop'
     '--nopull'

    Fixture returns list:
    repo, tag
    """

    mutually_exclusive_opts = [
        ["adcm_image", "adcm_images", "adcm_min_version"],
        ["staticimage", "adcm_images", "adcm_min_version"],
    ]
    # if more than one option that defines image params is used raise exception
    # pytest don't allow more convenient mechanisms to add mutually exclusive options.
    for opt_sets in mutually_exclusive_opts:
        if check_mutually_exclusive(cmd_opts, *opt_sets):
            raise Exception(
                "wrong using of import parameters %s are mutually exclusive"
                % ", ".join(opt_sets)
            )

    pull = not cmd_opts.nopull
    if cmd_opts.remote_docker:
        dc = docker.DockerClient(
            base_url=f"tcp://{cmd_opts.remote_docker}", timeout=120
        )
    else:
        dc = docker.from_env(timeout=120)

    params = dict()
    if cmd_opts.staticimage:
        params["repo"], params["tag"] = split_tag(cmd_opts.staticimage)
    # if image fixture was indirectly parametrized
    # use 'adcm_repo' and 'adcm_tag' from parametrisation
    if hasattr(request, "param"):
        params["adcm_repo"], params["adcm_tag"] = request.param
    # if there is no parametrization check if adcm_image option is passed
    elif cmd_opts.adcm_image:
        params["adcm_repo"], params["adcm_tag"] = split_tag(cmd_opts.adcm_image)

    if not (cmd_opts.dontstop or cmd_opts.staticimage):

        def fin():
            if init_image:
                image_name = "{}:{}".format(*init_image.values())
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

        # Set None for init image to avoid errors in finalizer
        # when get_initialized_adcm_image() fails
        init_image = None
        request.addfinalizer(fin)

    init_image = get_initialized_adcm_image(pull=pull, dc=dc, **params)

    return init_image["repo"], init_image["tag"]


def _adcm(image, cmd_opts, request) -> ADCM:
    repo, tag = image
    if cmd_opts.remote_docker:
        dw = DockerWrapper(base_url=f"tcp://{cmd_opts.remote_docker}")
        ip = cmd_opts.remote_docker.split(":")[0]
    else:
        dw = DockerWrapper()
        ip = (
            _get_connection_ip(cmd_opts.remote_executor_host)
            if cmd_opts.remote_executor_host
            else None
        )
        if ip and is_docker():
            if _get_if_type(ip) == "0":
                raise EnvironmentError(
                    "You are using network interface with 'bridge' "
                    "type while running inside container."
                    "There is no obvious way to get external ip in this case."
                    "Try running container with pytest with --net=host option"
                )
    adcm = dw.run_adcm(
        image=repo,
        tag=tag,
        pull=False,
        ip=ip,
        labels={"pytest_node_id": request.node.nodeid},
    )

    def fin():
        if not request.config.option.dontstop:
            gather = True
            try:
                if not request.node.rep_call.failed:
                    gather = False
            except AttributeError:
                # There is no rep_call attribute. Presumably test setup failed,
                # or fixture scope is not function. Will collect /adcm/data anyway
                pass
            if gather:
                with allure.step("Gather /adcm/data/ from ADCM container"):
                    file_name = f"ADCM Log {request.node.name}_{time.time()}"
                    reporter = _allure_reporter(request.config)
                    if reporter:
                        test_result = reporter.get_test(uuid=None)
                        with gather_adcm_data_from_container(adcm) as data:
                            reporter.attach_data(
                                uuid=uuid4(),
                                body=data,
                                name="{}.tgz".format(file_name),
                                extension="tgz",
                                parent_uuid=test_result.uuid,
                            )
                    else:
                        with gather_adcm_data_from_container(adcm) as data:
                            allure.attach(
                                body=data,
                                name="{}.tgz".format(file_name),
                                extension="tgz",
                            )

            _remove_hosts(adcm)

            try:
                adcm.container.kill()
            except DockerReadTimeout:
                pass

    request.addfinalizer(fin)

    adcm.api.auth(username="admin", password="admin")

    return adcm


def _allure_reporter(config) -> Optional[AllureReporter]:
    """Get Allure Reporter from pytest plugins"""
    listener: AllureListener = next(
        filter(
            lambda plugin: (isinstance(plugin, AllureListener)),
            dict(config.pluginmanager.list_name_plugin()).values(),
        ),
        None,
    )
    return listener.allure_logger if listener else None


def _get_connection_ip(remote_host: str):
    """
    Try to open connection to remote and get ip address of the interface used.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect((remote_host, 1))
    ip = s.getsockname()[0]
    s.close()
    return ip


def _get_if_name_by_ip(if_ip):
    """Get interface name by interface IP"""
    for adapter in ifaddr.get_adapters():
        for ip in adapter.ips:
            if ip.ip == if_ip:
                return adapter.name
    raise ValueError(f"IP {if_ip} does not match any network interface!")


def _get_if_type(if_ip):
    """
    Get interface type from /sys/class/net/{if_name}/type
    """
    if_name = _get_if_name_by_ip(if_ip)
    with open(f"/sys/class/net/{if_name}/type", "r") as f:
        return f.readline().strip()


def _remove_hosts(adcm: ADCM):
    client = ADCMClient(api=adcm.api)
    for cluster in Paging(client.cluster_list):
        cluster.delete()
    jobs = list()
    for host in Paging(client.host_list):
        if host.state != "removed" and "remove" in list(
            map(lambda x: getattr(x, "name"), host.action_list())
        ):
            jobs.append(remove_host(host))
    if jobs:
        for job in jobs:
            try:
                job.wait(timeout=60)
            # I case when host were not removed in requested timeout
            # we don't want it to affect test result
            except WaitTimeout:
                pass


# Legacy fixture should not be used in new tests!
@deprecated
@pytest.fixture(scope="module")
def adcm(image, cmd_opts, request):
    """Legacy ADCM object fixture. Do not use in new tests"""
    return _adcm(image, cmd_opts, request)


# Legacy fixture should not be used in new tests!
@deprecated
@pytest.fixture(scope="module")
def client(adcm):
    """Legacy api object fixture. Do not use in new tests"""
    return adcm.api.objects


##################################################
#                  S D K
##################################################
@allure.title("[MS] ADCM Container")
@pytest.fixture(scope="module")
def adcm_ms(image, cmd_opts, request) -> ADCM:
    """Runs adcm container from the previously initialized image.
    Operates '--dontstop' option.
    Returns authorized instance of ADCM object
    """
    return _adcm(image, cmd_opts, request)


@allure.title("[FS] ADCM Container")
@pytest.fixture(scope="function")
def adcm_fs(image, cmd_opts, request) -> ADCM:
    """Runs adcm container from the previously initialized image.
    Operates '--dontstop' option.
    Returns authorized instance of ADCM object
    """
    return _adcm(image, cmd_opts, request)


@allure.title("[SS] ADCM Container")
@pytest.fixture(scope="session")
def adcm_ss(image, cmd_opts, request) -> ADCM:
    """Runs adcm container from the previously initialized image.
    Operates '--dontstop' option.
    Returns authorized instance of ADCM object
    """
    return _adcm(image, cmd_opts, request)


@allure.title("[MS] ADCM Client")
@pytest.fixture(scope="module")
def sdk_client_ms(adcm_ms: ADCM) -> ADCMClient:
    """Returns ADCMClient object from adcm_client"""
    return ADCMClient(api=adcm_ms.api)


@allure.title("[FS] ADCM Client")
@pytest.fixture(scope="function")
def sdk_client_fs(adcm_fs: ADCM) -> ADCMClient:
    """Returns ADCMClient object from adcm_client"""
    return ADCMClient(api=adcm_fs.api)


@allure.title("[SS] ADCM Client")
@pytest.fixture(scope="session")
def sdk_client_ss(adcm_ss: ADCM) -> ADCMClient:
    """Returns ADCMClient object from adcm_client"""
    return ADCMClient(api=adcm_ss.api)


@allure.title("Pytest options")
@pytest.fixture(scope="session")
def cmd_opts(request):
    """Returns pytest request options object"""
    return request.config.option
