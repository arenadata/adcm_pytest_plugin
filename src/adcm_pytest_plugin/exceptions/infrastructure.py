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
"""Exceptions with infrastructure problems"""
from adcm_pytest_plugin.exceptions import BuiltinLikeAssertionError


class InfrastructureProblem(BuiltinLikeAssertionError):
    """Generic infrastructure exception"""

    default_msg: str = ""

    def __init__(self, msg=""):
        super().__init__(msg or self.__doc__)

    @classmethod
    def raise_if_suitable(cls, message):
        """Raise suitable infrastructure error if possible"""
        __tracebackhide__ = True  # pylint: disable=unused-variable

        if "timed out waiting for ping" in message:
            raise VmCreationError(message)
        if "Service Unavailable" in message or "Bad Gateway" in message:
            raise ExternalResourceUnavailable(message)
        if "Connection refused" in message or "Connection failure: timed out" in message:
            raise NetworkError(message)


class VmCreationError(InfrastructureProblem):
    """Something wrong with VM's creation"""


class ExternalResourceUnavailable(InfrastructureProblem):
    """Unavailable external resource"""


class NetworkError(InfrastructureProblem):
    """Network connection isn't stable"""


class DnsError(InfrastructureProblem):
    """DNS not resolved"""
