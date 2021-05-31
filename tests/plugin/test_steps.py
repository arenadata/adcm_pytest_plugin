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
Tests for plugin steps.
WARNING: don't run this test with xdist!!!
"""
import allure
import pytest

from adcm_pytest_plugin.steps.actions import run_cluster_action_and_assert_result
from adcm_pytest_plugin.utils import get_data_dir
from adcm_pytest_plugin.plugin import options

pytestmark = [allure.suite("Plugin steps")]


@pytest.mark.parametrize("bundle_dir", ["fail_action_cluster", "fail_multijob_cluster"])
def test_fail_action(sdk_client_fs, bundle_dir):
    """Run fail action and assert result"""
    bundle_dir_full = get_data_dir(__file__, bundle_dir)
    bundle = sdk_client_fs.upload_from_fs(bundle_dir_full)
    cluster = bundle.cluster_create("test_cluster")
    with pytest.raises(AssertionError) as action_run_exception:
        run_cluster_action_and_assert_result(cluster=cluster, action="fail_action")
    assert "Meant to fail" in str(action_run_exception.value), "No ansible error in AssertionError message"


@pytest.mark.parametrize("bundle_dir", ["simple_action_cluster"])
def test_verbose_actions_option(sdk_client_fs, bundle_dir):
    """
    Test verbose_actions option
    Assert attr presence
    Assert attr type
    Assert verbose state in action logs
    """
    bundle_dir_full = get_data_dir(__file__, bundle_dir)
    bundle = sdk_client_fs.upload_from_fs(bundle_dir_full)
    cluster = bundle.cluster_create("test_cluster")
    assert hasattr(options, "verbose_actions")
    assert isinstance(options.verbose_actions, bool)
    options.verbose_actions = True
    run_cluster_action_and_assert_result(cluster=cluster, action="simple_action")
    assert "verbosity: 4" in sdk_client_fs.job_list()[0].log_list()[0].content


@pytest.mark.parametrize("bundle_dir", ["simple_action_cluster"])
def test_verbose_actions_option_with_custom_verbose(sdk_client_fs, bundle_dir):
    """
    Test that custom verbose param for action
    has higher priority then verbose_actions option
    """
    bundle_dir_full = get_data_dir(__file__, bundle_dir)
    bundle = sdk_client_fs.upload_from_fs(bundle_dir_full)
    cluster = bundle.cluster_create("test_cluster")
    options.verbose_actions = True
    run_cluster_action_and_assert_result(
        cluster=cluster, action="simple_action", verbose=False
    )
    assert "verbosity: 4" not in sdk_client_fs.job_list()[0].log_list()[0].content
