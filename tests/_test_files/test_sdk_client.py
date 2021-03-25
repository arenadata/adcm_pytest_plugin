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
from adcm_client.objects import ADCMClient


def test_sdk_client(sdk_client_fs):
    """Checking that 'sdk_client_fs' create ADCMClient object"""
    assert isinstance(sdk_client_fs, ADCMClient), "ADCMClient not created"
