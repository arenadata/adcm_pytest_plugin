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
"""Class definitions for common objects"""

from dataclasses import dataclass

from adcm_client.objects import Action, Prototype


@dataclass
class ActionRunInfo:
    """Instance of a single action.run() invocation"""

    action_name: str
    parent_name: str
    parent_type: str
    expected_status: str

    def to_dict(self):
        """Convert object to dict"""
        return self.__dict__

    @classmethod
    def from_dict(cls, source_dict: dict):
        """Recreate instance from json string"""
        return cls(
            action_name=source_dict["action_name"],
            expected_status=source_dict["expected_status"],
            parent_name=source_dict["parent_name"],
            parent_type=source_dict["parent_type"],
        )

    # pylint: disable=protected-access
    @classmethod
    def from_action(cls, action: Action, expected_status: str = "Undefined"):
        """Create instance from Action obj"""
        proto = Prototype(api=action._api, prototype_id=action.prototype_id)
        return cls(
            action_name=action.name,
            expected_status=expected_status,
            parent_name=proto.name,
            parent_type=proto.type,
        )
