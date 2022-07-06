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

"""Custom types for usage in pytest and allure"""

import pytest


# pylint: disable=unused-argument
class SecureString(str):
    """
    Extension for the built-in str type
    When instansiated value will be addded to the set of sensitive data that will be masked in console outputs
    """

    def __new__(cls, value, *args, **kwargs):
        return super(SecureString, cls).__new__(cls, value)

    # pylint: disable=super-init-not-called
    def __init__(self, value, *args, **kwargs):
        if hasattr(pytest, "secure_data") and isinstance(pytest.secure_data, set):
            pytest.secure_data.add(value)
        else:
            pytest.secure_data = {
                value,
            }

    @staticmethod
    def make_all_nested_string_vals_secure(obj):
        """Mask all occurances of sensitive string in dict and list objects"""
        if isinstance(obj, str):
            obj = SecureString(obj)
        elif isinstance(obj, dict):
            for key, value in obj.items():
                obj[key] = SecureString.make_all_nested_string_vals_secure(value)
        elif isinstance(obj, list):
            obj = [SecureString(item) for item in obj]
        return obj


# pylint: enable=unused-argument
