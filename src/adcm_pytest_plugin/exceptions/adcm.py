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
"""Exceptions related to ADCM Client and requests to ADCM API"""
from adcm_pytest_plugin.exceptions import BuiltinLikeAssertionError


class ADCMError(BuiltinLikeAssertionError):
    """Generic ADCM error"""

    def __init__(self, msg=""):
        super().__init__(msg or self.__doc__)

    @classmethod
    def raise_if_suitable(cls, message):
        """Raise suitable ADCM error if possible"""
        __tracebackhide__ = True  # pylint: disable=unused-variable

        if "500 Internal Server Error" in message:
            raise ADCMInternalServerError(message)


class ADCMInternalServerError(ADCMError):
    """ADCM responded with 500 status code"""
