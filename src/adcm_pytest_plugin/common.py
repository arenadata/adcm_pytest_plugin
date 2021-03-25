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

import pytest


class Layer:
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
