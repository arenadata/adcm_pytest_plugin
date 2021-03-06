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

"""
Tests for plugin fixtures.
Does not contain tests with 'remote_executor_host', 'remote_docker', 'nopull' cmd opts
WARNING: don't run this test with xdist!!!
"""
import allure
import docker

from requests.exceptions import ReadTimeout as DockerReadTimeout
from tests.plugin.common import run_tests

pytestmark = [allure.suite("Plugin fixtures")]


def test_fixture_image(testdir):
    """
    Test image creating by fixture from plugin
    """
    result = run_tests(testdir, "test_image.py")

    # Asserts fixture teardown
    repo_with_tag = ""
    for line in result.outlines:
        if "test_image.py::test_image" in line:
            line = line.split("'")
            repo_with_tag = ":".join([line[1], line[3]])
    assert (
        len(docker.from_env().images.list(name=repo_with_tag)) == 0
    ), f"Found created image with '{repo_with_tag}' name"


def test_fixture_adcm(testdir):
    """
    Test ADCM running by fixture from plugin
    """
    result = run_tests(testdir, "test_adcm.py")

    # Asserts fixture teardown
    repo_with_tag = ""
    for line in result.outlines:
        if "test_adcm.py::test_adcm" in line:
            line = line.split("'")
            repo_with_tag = ":".join([line[1], line[3]])
    assert (
        len(
            docker.from_env().containers.list(
                filters=dict(ancestor=repo_with_tag), all=True
            )
        )
        == 0
    ), f"Found running or created container with '{repo_with_tag}' ancestor"


def test_fixture_sdk_client(testdir):
    """
    Test creating SDKClient object creating by fixture from plugin
    """
    run_tests(testdir, "test_sdk_client.py")


def test_fixture_image_staticimage(testdir):
    """
    Test image creating by fixture from plugin with 'staticimage' cmd opt
    """
    custom_image_name = "test_repo/test_image:test_tag"
    create_image_py_file = """
    def test_create_image(image):
        repo_name, tag = image
        # For teardown testing. This is needed to transfer result of executing fixture to outside.
        print((repo_name, tag))
    """
    run_tests(
        testdir,
        py_file=create_image_py_file,
        additional_opts=[f"--staticimage={custom_image_name}"],
    )

    client = docker.from_env()
    assert (
        len(client.images.list(name=custom_image_name)) == 1
    ), f"Do not found image with '{custom_image_name}' name"

    # Remove created static image after test
    for container in client.containers.list(filters=dict(ancestor=custom_image_name)):
        try:
            container.wait(condition="removed", timeout=30)
        except ConnectionError:
            # https://github.com/docker/docker-py/issues/1966 workaround
            pass
    client.images.remove(custom_image_name, force=True)


def test_fixture_adcm_dontstop(testdir):
    """
    Test ADCM running by fixture from plugin with 'dontstop' cmd opt
    """
    run_adcm_py_file = """
    def test_run_adcm(image, adcm_fs):
        repo_name, tag = image
        # For teardown testing. This is needed to transfer result of executing fixture to outside.
        print((repo_name, tag))
    """
    result = run_tests(
        testdir, py_file=run_adcm_py_file, additional_opts=["--dontstop"]
    )
    repo_with_tag = ""
    for line in result.outlines:
        if "test_fixture_adcm_dontstop.py::test_run_adcm" in line:
            line = line.split("'")
            repo_with_tag = ":".join([line[1], line[3]])
    container_list = docker.from_env().containers.list(
        filters=dict(ancestor=repo_with_tag)
    )

    assert (
        len(container_list) == 1
    ), f"Not found running or created container with '{repo_with_tag}' ancestor"

    # Stop and remove ADCM container after test
    for container in container_list:
        try:
            container.kill()
        except DockerReadTimeout:
            pass
