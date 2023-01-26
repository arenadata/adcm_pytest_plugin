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
from contextlib import suppress

import allure
import docker
import pytest
from requests.exceptions import ReadTimeout as DockerReadTimeout

from tests.plugin.common import run_tests

pytestmark = [allure.suite("Plugin fixtures")]


def test_fixture_image(testdir):
    """Test image creating by fixture from plugin"""
    run_tests(testdir, "test_image.py")
    assert pytest.test_retval, "Test has no return."
    repo_with_tag = ":".join(pytest.test_retval)
    # Asserts fixture teardown
    assert (
        len(docker.from_env().images.list(name=repo_with_tag)) == 0
    ), f"Found created image with '{repo_with_tag}' name"


def test_fixture_adcm(testdir):
    """Test ADCM running by fixture from plugin"""
    run_tests(testdir, "test_adcm.py")
    assert pytest.test_retval, "Test has no return."
    repo_with_tag = ":".join(pytest.test_retval)
    # Asserts fixture teardown
    assert (
        len(docker.from_env().containers.list(filters=dict(ancestor=repo_with_tag), all=True)) == 0
    ), f"Found running or created container with '{repo_with_tag}' ancestor"


def test_fixture_sdk_client(testdir):
    """Test creating SDKClient object creating by fixture from plugin"""
    run_tests(testdir, "test_sdk_client.py")


def test_fixture_adcm_dontstop(testdir):
    """Test ADCM running by fixture from plugin with 'dontstop' cmd opt"""
    run_adcm_py_file = """
    import pytest

    def test_run_adcm(image, adcm_fs):
        repo_name, tag = image
        # For teardown testing. This is needed to transfer result of executing fixture to outside.
        pytest.test_retval = repo_name, tag
    """
    run_tests(testdir, makepyfile_str=run_adcm_py_file, additional_opts=["--dontstop"])
    assert pytest.test_retval, "Test has no return."
    repo_with_tag = ":".join(pytest.test_retval)
    container_list = docker.from_env().containers.list(filters=dict(ancestor=repo_with_tag))

    assert len(container_list) == 1, f"Not found running or created container with '{repo_with_tag}' ancestor"

    # Stop and remove ADCM container after test
    for container in container_list:
        with suppress(DockerReadTimeout):
            container.kill()


def test_with_xdist(testdir):
    """Test distributed run of adcm_fs fixture.
    We cannot check inner test output due to output swallowing."""
    gw_count = 4
    test_content = f"""
    import pytest
    from adcm_client.objects import ADCMClient

    @pytest.mark.parametrize("arg", [*range({gw_count})])
    @pytest.mark.usefixtures("arg")
    def test_xdist_run(adcm_fs, adcm_api_credentials):
        username, password = adcm_api_credentials.values()
        ADCMClient(url=adcm_fs.url, user=username, password=password)
    """
    run_tests(
        testdir,  # keep from black
        makepyfile_str=test_content,
        additional_opts=[f"-n {gw_count}"],
        outcomes=dict(passed=gw_count),
    )


def test_fixture_image_with_dummy_data(testdir):
    """Test image creating and filling with dummy data by fixture from plugin"""
    run_tests(testdir, "test_image_with_dummy_data.py")


def test_upgradable_adcm_flag(testdir):
    """Test ADCM become upgradable if flag is True"""
    test_content = """
    import pytest
    from adcm_pytest_plugin.docker_utils import ADCM

    @pytest.mark.parametrize("adcm_is_upgradable", [True, False], indirect=True)
    def test_adcm_is_upgradable(adcm_fs: ADCM):
        assert len(adcm_fs.container_config.volumes) > 0
        for volume in adcm_fs.container_config.volumes.values():
            if volume["bind"] == "/adcm/shadow":
                break
        else:
            raise AssertionError("Volume for upgrade wasn't found")
    """
    run_tests(testdir, makepyfile_str=test_content, outcomes=dict(passed=1, failed=1))


def test_upgradable_adcm_flag_change_one_test(testdir):
    """Test that ADCM upgradable flag made ADCM upgradable exactly in one test"""
    test_content = """
    import pytest
    from adcm_pytest_plugin.docker_utils import ADCM

    @pytest.mark.parametrize("adcm_is_upgradable", [True], indirect=True)
    def test_adcm_is_upgradable(adcm_fs: ADCM):
        assert len(adcm_fs.container_config.volumes) > 0
        for volume in adcm_fs.container_config.volumes.values():
            if volume["bind"] == "/adcm/shadow":
                break
        else:
            raise AssertionError("Volume for upgrade wasn't found")

    def test_adcm_is_upgradable_fail(adcm_fs: ADCM):
        for volume in adcm_fs.container_config.volumes.values():
            assert volume["bind"] != "/adcm/shadow"
    """
    run_tests(testdir, makepyfile_str=test_content, outcomes=dict(passed=2))
