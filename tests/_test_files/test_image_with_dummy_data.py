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
WARNING: this file only for run in 'testdir.runpytest'
"""
import pytest


@pytest.fixture(scope="session")
def additional_adcm_init_config() -> dict:
    return {"fill_dummy_data": True}


def test_image_with_dummy_data(sdk_client_fs):
    """
    Check that 'image' fixture add dummy data
    when additional_adcm_init_config is redefined to return {"fill_dummy_data": True}
    """
    assert sdk_client_fs.cluster_list()
    clusters = sdk_client_fs.cluster_list()
    assert any(cluster.service_list() for cluster in clusters)
    assert sdk_client_fs.provider_list()
    assert sdk_client_fs.host_list()
    assert any(cluster.hostcomponent() for cluster in clusters)
    assert sdk_client_fs.job_list()
