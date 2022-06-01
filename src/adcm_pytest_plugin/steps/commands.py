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
import os.path
import subprocess
from contextlib import contextmanager
from typing import List, Generator, Tuple, Optional, Literal

import allure

from adcm_pytest_plugin.docker_utils import ADCM, is_file_presented_in_directory


_ACTIVATE_DEFAULT_VENV = "source /adcm/venv/default/bin/activate"
_RUN_MANAGE_PY = "python3 /adcm/python/manage.py"


@allure.step('Run ADCM command "dumpcluster" on cluster {cluster_id} to file {file_path}')
def dump_cluster(adcm: ADCM, cluster_id: int, file_path: str, password: str) -> None:
    """
    Dump cluster with "dumpcluster" command.
    """
    command = "dumpcluster"
    arguments = _prepare_cmd_arguments(adcm, f"{_RUN_MANAGE_PY} {command} -c {cluster_id} -o {file_path}")
    dump_dir, dump_file = os.path.dirname(file_path), os.path.basename(file_path)
    with _run_in_subprocess(arguments) as process:
        stdout, stderr = _type_password(process, password)
    if file_path in stdout and is_file_presented_in_directory(adcm.container, dump_file, dump_dir):
        return
    _interactive_command_failed(command, stdout, stderr)


@allure.step('Run ADCM command "loadcluster" from file {file_path}')
def load_cluster(adcm: ADCM, file_path: str, password: str) -> None:
    """
    Load cluster with "loadcluster" command.
    """
    command = "loadcluster"
    arguments = _prepare_cmd_arguments(adcm, f"{_RUN_MANAGE_PY} {command} {file_path}")
    with _run_in_subprocess(arguments) as process:
        stdout, stderr = _type_password(process, password)
    if "Load successfully ended" in stdout:
        return
    _interactive_command_failed(command, stdout, stderr)


def logrotate(
    adcm: ADCM, target: Optional[Literal["all", "job", "config", "nginx"]] = None, disable_logs: bool = False
):
    """
    Run rotation of logs (job/config/nginx) with "logrotate" command.
    """
    step_message = 'Run ADCM command "logrotate"'
    if options := " ".join(
        (f"`--target {target}`" if target is not None else "", "`--disable_logs`" if disable_logs else ""),
    ).strip():
        step_message += f"with options: {options}"

    with allure.step(step_message):
        command = "logrotate"
        exit_code, output = _run_with_docker_exec(
            adcm, f"{_ACTIVATE_DEFAULT_VENV} && {_RUN_MANAGE_PY} {command} {options}"
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
    return [
        "docker",
        "exec",
        "-i",
        adcm.container.name,
        "sh",
        "-c",
        f"{_ACTIVATE_DEFAULT_VENV} && {command}",
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
