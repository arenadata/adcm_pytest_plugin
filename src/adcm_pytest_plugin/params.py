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
Params helpers for ADCM parametrizing
Example:

    from adcm_pytest_plugin import params

    @params.https_only
    def test_some():
    ...
"""

import pytest

__all__ = ["including_https", "https_only", "clean_adcm_only"]


including_https = pytest.mark.parametrize(
    "adcm_https", [pytest.param(True, id="https"), pytest.param(False, id="http")], indirect=True
)
https_only = pytest.mark.parametrize("adcm_https", [True], indirect=True)

clean_adcm_only = pytest.mark.parametrize(
    "additional_adcm_init_config",
    [pytest.param({}, id="clean_adcm")],
    indirect=True,
)
