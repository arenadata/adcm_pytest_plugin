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

pytestmark = [allure.suite("Plugin steps")]


def test_fail_action(sdk_client_fs):
    """Run fail action and assert result"""
    bundle_dir = get_data_dir(__file__, "fail_action_cluster")
    bundle = sdk_client_fs.upload_from_fs(bundle_dir)
    cluster = bundle.cluster_create("test_cluster")
    with pytest.raises(AssertionError) as action_run_exception:
        run_cluster_action_and_assert_result(cluster=cluster, action="fail_action")
    assert "Meant to fail" in str(action_run_exception.value), "No ansible error in AssertionError message"
