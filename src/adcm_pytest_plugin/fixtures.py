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

import os
import socket
import uuid
from typing import Generator, Type

import allure
import ifaddr
import pytest
from _pytest.fixtures import SubRequest
from _pytest.terminal import TerminalReporter
from adcm_client.objects import ADCMClient
from allure_commons.utils import uuid4
from docker import DockerClient, from_env
from docker.utils import parse_repository_tag

from adcm_pytest_plugin.constants import DEFAULT_IP
from adcm_pytest_plugin.docker.adcm import ADCM
from adcm_pytest_plugin.docker.launchers import ADCMLauncher, ADCMWithPostgresLauncher, Stages
from adcm_pytest_plugin.docker.steps import (
    attach_adcm_data_dir,
    attach_postgres_data_dir,
    cleanup_ssl_certificate_directory,
    cleanup_via_truncate,
    generate_ssl_certificate_for_adcm,
    get_http_and_https_ports,
    get_only_http_port,
)
from adcm_pytest_plugin.docker.utils import is_docker
from adcm_pytest_plugin.params import ADCMVersionParam
from adcm_pytest_plugin.utils import allure_reporter, check_mutually_exclusive

##################################################
#              U T I L I T I E S
##################################################


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


def _print_adcm_url(reporter: TerminalReporter, adcm: ADCM):
    """Print ADCM URL link to the console output"""
    reporter.write_line("###################################")
    reporter.write_line(f"ADCM URL - {adcm.url}")
    reporter.write_line("###################################")


def _get_connection_ip(remote_host: str):
    """
    Try to open connection to remote and get ip address of the interface used.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)  # pylint: disable=no-member  # false positive pylint
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


def _adcm(request, container_launcher: ADCMLauncher):
    dontstop = request.config.option.dontstop

    container_launcher.run(
        run_arguments_mutator=lambda run_kwargs: {
            **run_kwargs,
            # Can't set nodeid before, so have to pass it to run
            "labels": {**run_kwargs.get("labels", {}), "pytest_node_id": request.node.nodeid},
        }
    )

    if dontstop:
        _print_adcm_url(request.config.pluginmanager.get_plugin("terminalreporter"), container_launcher.adcm)

    yield container_launcher.adcm

    if dontstop:
        _attach_adcm_url(request, container_launcher.adcm)
        return  # leave container intact

    container_launcher.stop(request)


##################################################
#              G E N E R A L
##################################################


# pylint: disable=redefined-outer-name


@allure.title("Pytest options")
@pytest.fixture(scope="session")
def cmd_opts(request):
    """Returns pytest request options object"""
    cmd_opts = request.config.option
    mutually_exclusive_opts = [
        ["adcm_image", "adcm_images", "adcm_min_version"],
    ]
    # if more than one option that defines image params is used raise exception
    # pytest don't allow more convenient mechanisms to add mutually exclusive options.
    for opt_sets in mutually_exclusive_opts:
        if check_mutually_exclusive(cmd_opts, *opt_sets):
            raise Exception(f"wrong using of import parameters {', '.join(opt_sets)} are mutually exclusive")

    return cmd_opts


@pytest.fixture(scope="session")
def docker_client(cmd_opts) -> DockerClient:
    if cmd_opts.remote_docker:
        return DockerClient(base_url=f"tcp://{cmd_opts.remote_docker}", timeout=120)

    return from_env(timeout=120)


# pylint: disable=redefined-outer-name
@allure.title("Bind container IP")
@pytest.fixture(scope="session")
def bind_container_ip(cmd_opts) -> str:
    """Get ip binding to container"""
    if cmd_opts.remote_docker:
        return cmd_opts.remote_docker.split(":")[0]

    if not cmd_opts.remote_executor_host:
        return DEFAULT_IP

    ip = _get_connection_ip(cmd_opts.remote_executor_host)
    if ip and is_docker() and _get_if_type(ip) == "0":
        raise EnvironmentError(
            "You are using network interface with 'bridge' "
            "type while running inside container."
            "There is no obvious way to get external ip in this case."
            "Try running container with pytest with --net=host option"
        )
    return ip


##################################################
#          S T A R T U P   A D C M
##################################################


@allure.title("Image version to base ADCM upon")
@pytest.fixture(scope="session")
def image(request, cmd_opts, docker_client) -> ADCMVersionParam:
    """
    Handle what image version(s) will be used to start ADCM
    """

    if hasattr(request, "param"):
        # image fixture was indirectly parametrized
        # in most cases it's the way to "correctly" launch tests on various ADCM versions
        param = request.param
        if isinstance(param, ADCMVersionParam):  # new version of parametrization that provides "full" info
            version = request.param
        else:  # consider it's a legacy parametrization, use 'repo' and 'tag' from parametrization
            repository, tag = request.param
            version = ADCMVersionParam(repository=repository, tag=tag, with_postgres=False)
    elif cmd_opts.adcm_image:
        # if there is no parametrization check if adcm_image option is passed
        repository, tag = parse_repository_tag(cmd_opts.adcm_image)
        version = ADCMVersionParam(repository=repository, tag=tag, with_postgres=not cmd_opts.no_postgres)
    else:
        # set default otherwise
        version = ADCMVersionParam(repository="hub.arenadata.io/adcm/adcm", tag="latest", with_postgres=True)

    with allure.step(f"ADCM image settings: {version}"):
        ...

    if cmd_opts.nopull:
        with allure.step("Skip pulling ADCM from remote repo"):
            return version

    with allure.step(f'Pull ADCM "{version.tag}" from repository "{version.repository}"'):
        docker_client.images.pull(repository=version.repository, tag=version.tag)

    return version


@allure.title("Pick ADCM implementation")
@pytest.fixture(scope="session")
def launcher_class(image) -> Type[ADCMLauncher]:
    """
    Decide what ADCM launcher to use
    """
    return ADCMWithPostgresLauncher if image.with_postgres else ADCMLauncher


@allure.title("[SS] ADCM upgradable flag")
@pytest.fixture(scope="session")
def adcm_is_upgradable(request) -> bool:
    """Set flag that controls either ADCM will be upgradable or not"""
    if hasattr(request, "param") and request.param:
        return True
    return False


@allure.title("[SS] ADCM https flag")
@pytest.fixture(scope="session")
def adcm_https(request) -> bool:
    """Set flag that controls either will ADCM have SSL cert and opened https port or not"""
    if hasattr(request, "param") and request.param:
        return True
    return False


@allure.title("Prepare lifecycle stages")
@pytest.fixture(scope="session")
def stages(cmd_opts, adcm_https, launcher_class, adcm_is_upgradable):
    prepare_image_steps = []
    prepare_run_arguments_steps = []
    on_cleanup_steps = []
    pre_stop_steps = [attach_adcm_data_dir]

    if hasattr(cmd_opts, "debug_owner") and (owner := cmd_opts.debug_owner):
        prepare_run_arguments_steps.append(lambda _1, _2: {"labels": {"debug_owner": owner}})

    if build_tag := os.environ.get("BUILD_TAG"):
        prepare_run_arguments_steps.append(lambda _, d: {"labels": {"jenkins-job": build_tag, **d.get("labels", {})}})

    if adcm_https:
        prepare_image_steps.append(generate_ssl_certificate_for_adcm)
        # prepare_run_arguments_steps.append(mount_ssl_certs)
        prepare_run_arguments_steps.append(get_http_and_https_ports)
        on_cleanup_steps.append(cleanup_ssl_certificate_directory)
    else:
        prepare_run_arguments_steps.append(get_only_http_port)

    # ADCM version based modifiers
    if launcher_class == ADCMWithPostgresLauncher:
        pre_stop_steps += [attach_postgres_data_dir, cleanup_via_truncate]
    else:
        if adcm_is_upgradable:
            prepare_run_arguments_steps.append(
                lambda _1, d: {
                    "volumes": {**d.get("volumes", {}), str(uuid.uuid4())[-12:]: {"bind": "/adcm/data", "mode": "rw"}}
                }
            )

    return Stages(
        prepare_image=prepare_image_steps,
        prepare_run_arguments=prepare_run_arguments_steps,
        pre_stop=pre_stop_steps,
        on_cleanup=on_cleanup_steps,
    )


@allure.title("Initiate launcher")
@pytest.fixture(scope="session")
def launcher(
    image: ADCMVersionParam, docker_client, bind_container_ip, launcher_class, stages
) -> Generator[ADCMLauncher, None, None]:
    launcher = launcher_class(
        adcm_image=(image.repository, image.tag),
        docker_client=docker_client,
        bind_ip=bind_container_ip,
        stages=stages,
    )

    launcher.prepare()

    yield launcher

    launcher.cleanup()


@allure.title("[MS] ADCM Container")
@pytest.fixture(scope="module")
def adcm_ms(request, launcher) -> Generator[ADCM, None, None]:
    yield from _adcm(request=request, container_launcher=launcher)


@allure.title("[FS] ADCM Container")
@pytest.fixture(scope="function")
def adcm_fs(request, launcher) -> Generator[ADCM, None, None]:
    yield from _adcm(request=request, container_launcher=launcher)


@allure.title("[SS] ADCM Container")
@pytest.fixture(scope="session")
def adcm_ss(request, launcher) -> Generator[ADCM, None, None]:
    yield from _adcm(request=request, container_launcher=launcher)


@allure.title("[FS] Additional ADCM Container")
@pytest.fixture()
def extra_adcm_fs(request, launcher) -> Generator[ADCM, None, None]:
    yield from _adcm(request=request, container_launcher=launcher)


##################################################
#                  S D K
##################################################


@allure.title("ADCM credentials")
@pytest.fixture(scope="session")
def adcm_api_credentials() -> dict:
    """ADCM credentials for use in tests"""
    return {"user": "admin", "password": "admin"}


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
