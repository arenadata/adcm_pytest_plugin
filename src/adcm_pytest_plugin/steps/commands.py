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
from typing import List, Generator, Tuple

import allure

from adcm_pytest_plugin.docker_utils import ADCM, is_file_presented_in_directory


@allure.step('Run ADCM command "dumpcluster" on cluster {cluster_id} to file {file_path}')
def dump_cluster(adcm: ADCM, cluster_id: int, file_path: str, password: str) -> None:
    """
    Dump cluster with "dumpcluster" command.
    """
    command = "dumpcluster"
    arguments = _prepare_cmd_arguments(adcm, f"python3 /adcm/python/manage.py {command} -c {cluster_id} -o {file_path}")
    dump_dir, dump_file = os.path.dirname(file_path), os.path.basename(file_path)
    with _run_in_subprocess(arguments) as process:
        stdout, stderr = _type_password(process, password)
    if file_path in stdout and is_file_presented_in_directory(adcm.container, dump_file, dump_dir):
        return
    _command_failed(command, stdout, stderr)


@allure.step('Run ADCM command "loadcluster" from file {file_path}')
def load_cluster(adcm: ADCM, file_path: str, password: str) -> None:
    """
    Load cluster with "loadcluster" command.
    """
    command = "loadcluster"
    arguments = _prepare_cmd_arguments(adcm, f"python3 /adcm/python/manage.py {command} {file_path}")
    with _run_in_subprocess(arguments) as process:
        stdout, stderr = _type_password(process, password)
    if file_path in stdout:
        return
    _command_failed(command, stdout, stderr)


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
        f"source /adcm/venv/default/bin/activate && {command}",
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


def _command_failed(command: str, stdout_log: str, stderr_log: str):
    """
    Attach logs of command and raise AssertionError
    """
    allure.attach(stdout_log, name="stdout", attachment_type=allure.attachment_type.TEXT)
    allure.attach(stderr_log, name="stderr", attachment_type=allure.attachment_type.TEXT)
    raise AssertionError(f'Command "{command}" failed.\nCheck attachments for more details')
