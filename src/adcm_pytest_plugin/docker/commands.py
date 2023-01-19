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

"""Execute ADCM Django commands"""

import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Collection, Generator, List, Literal, Optional, Tuple

import allure
import requests
from version_utils import rpm

from adcm_pytest_plugin.docker.adcm import ADCM
from adcm_pytest_plugin.docker.utils import is_file_presented_in_directory

_DEFAULT_VENV = "/adcm/venv/default/bin/activate"
_MANAGE_PY = "/adcm/python/manage.py"


def _run_command(adcm: ADCM, command: str, options: Optional[Collection[str]] = ()):
    activate_venv, python = _get_command_prefixes(adcm)
    with allure.step(f'Run ADCM command "{command}"' + (f" with options {' '.join(options)}" if options else "")):
        exit_code, output = _run_with_docker_exec(
            adcm,
            [
                "sh",
                "-c",
                f"{activate_venv} {_DEFAULT_VENV} && {python} {_MANAGE_PY} "
                f"{command} {' '.join(options) if options else ''}",
            ],
        )
        if exit_code == 0:
            return
        _docker_exec_command_failed(command, exit_code, output)


def _run_with_docker_exec(adcm: ADCM, args: List[str]) -> Tuple[int, bytes]:
    """
    Execute command given in arguments with `exec_run`
    """
    return adcm.container.exec_run(args)


def _prepare_cmd_arguments(adcm: ADCM, command: str) -> List[str]:
    """
    Prepare "args" required to execute interactive ADCM command from terminal
    """
    activate_venv, _ = _get_command_prefixes(adcm)
    return [
        "docker",
        "exec",
        "-i",
        adcm.container.name,
        "sh",
        "-c",
        f"{activate_venv} {_DEFAULT_VENV} && {command}",
    ]


@contextmanager
def _run_in_subprocess(args: List[str]) -> Generator[subprocess.Popen, None, None]:
    """
    Start subprocess to communicate with
    """
    process = subprocess.Popen(
        args,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        yield process
    finally:
        process.terminate()


def _type_password(process: subprocess.Popen, password: str) -> Tuple[str, str]:
    """
    Type password and return stdout and stderr decoded from bytes
    """
    stdout, stderr = process.communicate(password.encode("utf-8"))
    return stdout.decode("utf-8"), stderr.decode("utf-8")


def _interactive_command_failed(command: str, stdout_log: str, stderr_log: str):
    """
    Attach logs of command and raise AssertionError
    when interactive command execution (ran with Popen) failed
    """
    allure.attach(stdout_log, name="stdout", attachment_type=allure.attachment_type.TEXT)
    allure.attach(stderr_log, name="stderr", attachment_type=allure.attachment_type.TEXT)
    raise AssertionError(f'Command "{command}" failed.\nCheck attachments for more details')


def _docker_exec_command_failed(command: str, exit_code: int, output: bytes):
    """
    Attach logs of command and raise AssertionError
    when command execution (ran with `docker_exec`) failed
    """
    allure.attach(
        output.decode("utf-8"), name="command output (from `docker_exec`)", attachment_type=allure.attachment_type.TEXT
    )
    raise AssertionError(f'Command "{command}" failed with {exit_code} exit code.\nCheck attachments for more details.')


def _get_command_prefixes(adcm: ADCM) -> Tuple[str, str]:
    """Get venv activation and python prefixes"""
    if rpm.compare_versions(_get_adcm_version(adcm), "2022.10.04.17") > 0:
        return ".", "python"
    return "source", "python3"


def _get_adcm_version(adcm: ADCM) -> str:
    response = requests.get(f"{adcm.url}/api/v1/info/", timeout=5)
    response.raise_for_status()
    return response.json()["adcm_version"]


@allure.step('Run ADCM command "dumpcluster" on cluster {cluster_id} to file {file_path}')
def dump_cluster(adcm: ADCM, cluster_id: int, file_path: str, password: str) -> None:
    """
    Dump cluster with "dumpcluster" command.
    """
    command = "dumpcluster"
    _, python = _get_command_prefixes(adcm)
    arguments = _prepare_cmd_arguments(adcm, f"{python} {_MANAGE_PY} {command} -c {cluster_id} -o {file_path}")
    file = Path(file_path)
    with _run_in_subprocess(arguments) as process:
        stdout, stderr = _type_password(process, password)
    if file_path in stdout and is_file_presented_in_directory(adcm.container, file.name, file.parent):
        return
    _interactive_command_failed(command, stdout, stderr)


@allure.step('Run ADCM command "loadcluster" from file {file_path}')
def load_cluster(adcm: ADCM, file_path: str, password: str) -> None:
    """
    Load cluster with "loadcluster" command.
    """
    command = "loadcluster"
    _, python = _get_command_prefixes(adcm)
    arguments = _prepare_cmd_arguments(adcm, f"{python} {_MANAGE_PY} {command} {file_path}")
    with _run_in_subprocess(arguments) as process:
        stdout, stderr = _type_password(process, password)
    if "Load successfully ended" in stdout:
        return
    _interactive_command_failed(command, stdout, stderr)


def logrotate(
    adcm: ADCM, target: Optional[Literal["all", "job", "config", "nginx"]] = None, disable_logs: bool = False
) -> None:
    """
    Run rotation of logs (job/config/nginx) with "logrotate" command.
    """
    options = []
    if target is not None:
        options.append(f"--target {target}")
    if disable_logs:
        options.append("--disable-logs")

    _run_command(adcm, "logrotate", options)


def clearaudit(adcm: ADCM) -> None:
    """
    Run audit log cleanup with "clearaudit" command
    """
    _run_command(adcm, "clearaudit")


def dumpdata(adcm: ADCM, filename: str) -> None:
    """
    Dump ADCM DB data to a given file
    """
    _run_command(adcm, "dumpdata", [">", filename])
