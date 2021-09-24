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
"""Fixtures of ADCM image and ADCM client"""
import socket
import time
import uuid
from contextlib import suppress
from typing import Generator

import allure
import docker
import ifaddr
import pytest
from _pytest.fixtures import SubRequest
from adcm_client.objects import ADCMClient
from allure_commons.utils import uuid4
from docker.utils import parse_repository_tag
from requests.exceptions import ReadTimeout as DockerReadTimeout

from adcm_pytest_plugin import utils
from .docker_utils import (
    ADCM,
    ADCMInitializer,
    ContainerConfig,
    DockerWrapper,
    gather_adcm_data_from_container,
    is_docker,
    remove_container_volumes,
    remove_docker_image,
)
from .utils import check_mutually_exclusive, allure_reporter

DATADIR = utils.get_data_dir(__file__)

__all__ = [
    "image",
    "cmd_opts",
    "adcm_fs",
    "adcm_ss",
    "adcm_ms",
    "adcm_is_upgradable",
    "sdk_client_ms",
    "sdk_client_fs",
    "sdk_client_ss",
    "adcm_api_credentials",
    "additional_adcm_init_config",
]


@allure.title("ADCM credentials")
@pytest.fixture(scope="session")
def adcm_api_credentials() -> dict:
    """ADCM credentials for use in tests"""
    return {"user": "admin", "password": "admin"}


@allure.title("Additional ADCM init config")
@pytest.fixture(scope="session")
def additional_adcm_init_config() -> dict:
    """
    Add options for ADCM init.
    Redefine this fixture in the actual project to alter additional options of ADCM initialisation.
    Ex. If this fixture will return {"fill_dummy_data": True}
    then on the init stage dummy objects will be added to ADCM image
    """
    return {}


# pylint: disable=W0621
@allure.title("ADCM Image")
@pytest.fixture(scope="session")
def image(request, cmd_opts, adcm_api_credentials, additional_adcm_init_config):
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
            raise Exception(f"wrong using of import parameters {', '.join(opt_sets)} are mutually exclusive")

    pull = not cmd_opts.nopull
    if cmd_opts.remote_docker:
        docker_client = docker.DockerClient(base_url=f"tcp://{cmd_opts.remote_docker}", timeout=120)
    else:
        docker_client = docker.from_env(timeout=120)

    params = {}
    if cmd_opts.staticimage:
        params["repo"], params["tag"] = parse_repository_tag(cmd_opts.staticimage)
    # if image fixture was indirectly parametrized
    # use 'adcm_repo' and 'adcm_tag' from parametrisation
    if hasattr(request, "param"):
        params["adcm_repo"], params["adcm_tag"] = request.param
    # if there is no parametrization check if adcm_image option is passed
    elif cmd_opts.adcm_image:
        params["adcm_repo"], params["adcm_tag"] = parse_repository_tag(cmd_opts.adcm_image)

    init_image = ADCMInitializer(
        pull=pull,
        dc=docker_client,
        adcm_api_credentials=adcm_api_credentials,
        **params,
        **additional_adcm_init_config,
    ).get_initialized_adcm_image()

    yield init_image["repo"], init_image["tag"]

    if cmd_opts.dontstop or cmd_opts.staticimage:
        return  # leave image intact

    remove_docker_image(**init_image, dc=docker_client)


def _adcm(image, cmd_opts, request, upgradable=False) -> Generator[ADCM, None, None]:
    repo, tag = image
    labels = {"pytest_node_id": request.node.nodeid}
    # this option can be passed from private adcm-pytest-tools (check its README.md for more info)
    if hasattr(cmd_opts, "debug_owner") and cmd_opts.debug_owner:
        labels["debug_owner"] = cmd_opts.debug_owner
    docker_url = None
    if cmd_opts.remote_docker:
        docker_url = f"tcp://{cmd_opts.remote_docker}"
        docker_wrapper = DockerWrapper(base_url=docker_url)
        ip = cmd_opts.remote_docker.split(":")[0]
    else:
        docker_wrapper = DockerWrapper()
        ip = _get_connection_ip(cmd_opts.remote_executor_host) if cmd_opts.remote_executor_host else None
        if ip and is_docker() and _get_if_type(ip) == "0":
            raise EnvironmentError(
                "You are using network interface with 'bridge' "
                "type while running inside container."
                "There is no obvious way to get external ip in this case."
                "Try running container with pytest with --net=host option"
            )
    volumes = {}
    if upgradable:
        volume_name = str(uuid.uuid4())[-12:]
        volumes.update({volume_name: {"bind": "/adcm/shadow", "mode": "rw"}})
    adcm = ADCM(
        docker_wrapper=docker_wrapper,
        container_config=ContainerConfig(
            image=repo, tag=tag, pull=False, bind_ip=ip, labels=labels, volumes=volumes, docker_url=docker_url
        ),
    )

    yield adcm

    if request.config.option.dontstop:
        _attach_adcm_url(request, adcm)
        return  # leave container intact

    gather = True
    # If there is no rep_call attribute, presumably test setup failed,
    # or fixture scope is not function. Will collect /adcm/data anyway.
    with suppress(AttributeError):
        if not request.node.rep_call.failed:
            gather = False
    if gather:
        _attach_adcm_logs(request, adcm)

    with suppress(DockerReadTimeout):
        adcm.stop()

    remove_container_volumes(adcm.container, docker_wrapper.client)


@allure.step("Gather /adcm/data/ from ADCM container")
def _attach_adcm_logs(request: SubRequest, adcm: ADCM):
    """Gather /adcm/data/ form the ADCM container and attach it to the Allure Report"""
    file_name = f"ADCM Log {request.node.name}_{time.time()}"
    reporter = allure_reporter(request.config)
    if reporter:
        test_result = reporter.get_test(uuid=None)
        with gather_adcm_data_from_container(adcm) as data:
            reporter.attach_data(
                uuid=uuid4(),
                body=data,
                name=f"{file_name}.tgz",
                extension="tgz",
                parent_uuid=test_result.uuid,
            )
    else:
        with gather_adcm_data_from_container(adcm) as data:
            allure.attach(
                body=data,
                name=f"{file_name}.tgz",
                extension="tgz",
            )


def _attach_adcm_url(request: SubRequest, adcm: ADCM):
    """Attach ADCM URL link to the Allure Report for the further access"""
    attachment_name = "ADCM URL"
    reporter = allure_reporter(request.config)
    if reporter:
        test_result = reporter.get_test(uuid=None)
        reporter.attach_data(
            uuid=uuid4(),
            body=adcm.url,
            name=attachment_name,
            extension="text",
            parent_uuid=test_result.uuid,
        )
    else:
        allure.attach(
            body=adcm.url,
            name=attachment_name,
            extension="text",
        )


def _get_connection_ip(remote_host: str):
    """
    Try to open connection to remote and get ip address of the interface used.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.connect((remote_host, 1))
    ip = sock.getsockname()[0]
    sock.close()
    return ip


def _get_if_name_by_ip(if_ip):
    """Get interface name by interface IP"""
    for adapter in ifaddr.get_adapters():
        for ip_addr in adapter.ips:
            if ip_addr.ip == if_ip:
                return adapter.name
    raise ValueError(f"IP {if_ip} does not match any network interface!")


def _get_if_type(if_ip):
    """
    Get interface type from /sys/class/net/{if_name}/type
    """
    if_name = _get_if_name_by_ip(if_ip)
    with open(f"/sys/class/net/{if_name}/type", "r", encoding="utf-8") as file:
        return file.readline().strip()


##################################################
#                  S D K
##################################################
@allure.title("[MS] ADCM Container")
@pytest.fixture(scope="module")
def adcm_ms(image, cmd_opts, request, adcm_is_upgradable: bool) -> Generator[ADCM, None, None]:
    """Runs adcm container from the previously initialized image.
    Operates '--dontstop' option.
    Returns authorized instance of ADCM object
    """
    yield from _adcm(image, cmd_opts, request, upgradable=adcm_is_upgradable)


@allure.title("[FS] ADCM Container")
@pytest.fixture(scope="function")
def adcm_fs(image, cmd_opts, request, adcm_is_upgradable: bool) -> Generator[ADCM, None, None]:
    """Runs adcm container from the previously initialized image.
    Operates '--dontstop' option.
    Returns authorized instance of ADCM object
    """
    yield from _adcm(image, cmd_opts, request, upgradable=adcm_is_upgradable)


@allure.title("[SS] ADCM Container")
@pytest.fixture(scope="session")
def adcm_ss(image, cmd_opts, request, adcm_is_upgradable: bool) -> Generator[ADCM, None, None]:
    """Runs adcm container from the previously initialized image.
    Operates '--dontstop' option.
    Returns authorized instance of ADCM object
    """
    yield from _adcm(image, cmd_opts, request, upgradable=adcm_is_upgradable)


@allure.title("[SS] ADCM upgradable flag")
@pytest.fixture(scope="session")
def adcm_is_upgradable(request) -> bool:
    """Set flag that controls either ADCM will be upgradable or not"""
    if hasattr(request, "param") and request.param:
        return True
    return False


@allure.title("[MS] ADCM Client")
@pytest.fixture(scope="module")
def sdk_client_ms(adcm_ms: ADCM, adcm_api_credentials) -> ADCMClient:
    """Returns ADCMClient object from adcm_client"""
    return ADCMClient(url=adcm_ms.url, **adcm_api_credentials)


@allure.title("[FS] ADCM Client")
@pytest.fixture(scope="function")
def sdk_client_fs(adcm_fs: ADCM, adcm_api_credentials) -> ADCMClient:
    """Returns ADCMClient object from adcm_client"""
    return ADCMClient(url=adcm_fs.url, **adcm_api_credentials)


@allure.title("[SS] ADCM Client")
@pytest.fixture(scope="session")
def sdk_client_ss(adcm_ss: ADCM, adcm_api_credentials) -> ADCMClient:
    """Returns ADCMClient object from adcm_client"""
    return ADCMClient(url=adcm_ss.url, **adcm_api_credentials)


@allure.title("Pytest options")
@pytest.fixture(scope="session")
def cmd_opts(request):
    """Returns pytest request options object"""
    return request.config.option
