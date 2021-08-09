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
"""Module with custom collection of exceptions"""


class BuiltinLikeAssertionError(AssertionError):
    """
    Allows to make exception builtin-like
    Builtin module gets rid module prefix when exception raised
    For example, error:
        adcm_pytest_plugin.exceptions.bundles.AnsibleError: Error in ansible logic
    will be:
        AnsibleError: Error in ansible logic
    """

    def __init__(self, *args):
        super().__init__(*args)
        self.__class__.__module__ = "builtins"
