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
"""Common methods and classes"""

import pytest
import allure
from .utils import get_data_dir


class Layer:  # pylint: disable=too-few-public-methods
    """
    Decorators of allure layers
    Example:

        @Layer.UI
        def test_ui():
            pass


        @Layer.API
        def test_api():
            pass
    """

    UI = pytest.mark.allure_label("UI", label_type="layer")
    API = pytest.mark.allure_label("API", label_type="layer")
    Unit = pytest.mark.allure_label("Unit", label_type="layer")


@allure.title("Add dummy objects to ADCM")
def add_dummy_objects_to_adcm(adcm_client):
    """Add a bunch of dummy objects to ADCM"""
    with allure.step("Create provider"):
        provider_bundle = adcm_client.upload_from_fs(get_data_dir(__file__, "provider"))
        provider = provider_bundle.provider_prototype().provider_create(name="Pre-uploaded provider")
    with allure.step("Create cluster for the further import"):
        cluster_to_import_bundle = adcm_client.upload_from_fs(get_data_dir(__file__, "cluster_to_import"))
        cluster_to_import = cluster_to_import_bundle.cluster_prototype().cluster_create(
            name="Pre-uploaded cluster for the import"
        )
    with allure.step("Create a cluster with service"):
        cluster_bundle = adcm_client.upload_from_fs(get_data_dir(__file__, "cluster_with_service"))
        cluster = cluster_bundle.cluster_prototype().cluster_create(name="Pre-uploaded cluster with services")
        cluster.bind(cluster_to_import)
    with allure.step("Add services"):
        service_first = cluster.service_add(name="First service")
        service_second = cluster.service_add(name="Second service")
    with allure.step("Add hosts"):
        host_first = provider.host_create(fqdn="pre-uploaded-host-in-cluster")
        host_second = provider.host_create(fqdn="pre-uploaded-host-in-cluster-second")
        cluster.host_add(host_first)
        cluster.host_add(host_second)
    with allure.step("Set components"):
        cluster.hostcomponent_set(
            (host_first, service_first.component(name="first")),
            (host_second, service_first.component(name="second")),
            (host_second, service_second.component(name="third")),
        )
    with allure.step("Run task"):
        task = cluster.action(name="action_on_cluster").run()
        task.wait()
