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

import re
import tarfile
from contextlib import contextmanager, suppress
from io import BytesIO
from os import system
from warnings import warn

import requests
from docker.errors import APIError, NotFound
from docker.models.containers import Container, ExecResult

from adcm_pytest_plugin.utils import random_string, retry_on_error


def _run_command_and_assert_result(command: str, fail_message: str):
    """Run `os.system` with given command and assert that result code is equal to 0"""
    assert (result := system(command)) == 0, f"Operation failed. Exit code was {result}. Message: {fail_message}"


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


def get_successful_output(exec_run_result: ExecResult) -> str:
    output = exec_run_result.output.decode().splitlines()

    if exec_run_result.exit_code != 0:
        raise RuntimeError(f"Command failed:\n{output}")

    return output


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
    file_obj = BytesIO()
    for i in stream:
        file_obj.write(i)
    file_obj.seek(0)
    with tarfile.open(mode="r", fileobj=file_obj) as tar:
        return tar.extractfile(filename)


def remove_container_volumes(container: Container):
    """
    Remove volumes related to the given container.
    Note that container should be removed before function call.
    """

    for name in (mount["Name"] for mount in container.attrs["Mounts"] if mount["Type"] == "volume"):
        with suppress(NotFound):
            retry_on_error(container.client.volumes.get(name).remove, err_to_ignore_=APIError, err_to_reraise_=NotFound)


@contextmanager
def suppress_docker_wait_error():
    """
    Suppress requests ConnectionError to avoid unhandled docker-py exception
    """
    try:
        yield
    except requests.exceptions.ConnectionError:
        warn(
            "Failed to wait container state at the specified timeout\n"
            "It's workaround of docker-py error, see https://github.com/docker/docker-py/issues/1966"
        )


def is_file_presented_in_directory(container: Container, file: str, directory: str) -> bool:
    """
    Check if file is presented in directory in container
    """
    return file in container.exec_run(["ls", "-a", directory]).output.decode("utf-8")


def copy_file_to_container(from_container: Container, to_container: Container, from_path: str, to_path: str) -> None:
    """
    Copy file from one container to another through local temp directory in /tmp
    """
    local_tempdir = f"{from_container.name}-to-{to_container.name}-{random_string(6)}"
    _run_command_and_assert_result(
        f"docker cp {from_container.name}:{from_path} /tmp/{local_tempdir}",
        "Copy from container to filesystem failed.",
    )
    _run_command_and_assert_result(
        f"docker cp /tmp/{local_tempdir} {to_container.name}:{to_path}", "Copy to container failed."
    )


def get_network_settings(container: Container) -> dict:
    return container.client.api.inspect_container(container.id)["NetworkSettings"]
