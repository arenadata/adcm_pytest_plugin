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
"""Class definitions for actions related objects"""
import json
import os
from dataclasses import dataclass
from typing import List
from collections import defaultdict

from adcm_client.objects import Action, Prototype, Bundle


@dataclass
class ActionRunInfo:
    """Instance of a single action.run() invocation"""

    action_name: str
    parent_name: str
    parent_type: str
    bundle_info: str
    expected_status: str
    called_from: str

    def to_dict(self):
        """Convert object to dict"""
        return self.__dict__

    @classmethod
    def from_dict(cls, source_dict: dict):
        """Recreate instance from json string"""
        return cls(**{key: source_dict[key] for key in cls.__dict__["__annotations__"].keys()})

    # pylint: disable=protected-access
    @classmethod
    def from_action(cls, action: Action, expected_status: str = "Undefined"):
        """Create instance from Action obj"""
        proto = Prototype(api=action._api, prototype_id=action.prototype_id)
        bundle = Bundle(api=action._api, bundle_id=proto.bundle_id)
        return cls(
            action_name=action.name,
            expected_status=expected_status,
            parent_name=proto.name,
            parent_type=proto.type,
            bundle_info=f"{bundle.name}_{bundle.version}_{bundle.edition}",
            called_from=os.getenv("PYTEST_CURRENT_TEST", "Undefined"),
        )


@dataclass
class ActionsSpec:
    """Info about actions from prototype"""

    actions: List[str]
    parent_name: str
    parent_type: str
    bundle_info: str

    def to_dict(self):
        """Convert object to dict"""
        return self.__dict__

    @property
    def uniq_id(self):
        """Get identifier"""
        return f"{self.bundle_info}_{self.parent_type}_{self.parent_name}"

    @classmethod
    def from_dict(cls, source_dict: dict):
        """Recreate instance from json string"""
        return cls(**{key: source_dict[key] for key in cls.__dict__["__annotations__"].keys()})

    # pylint: disable=protected-access
    @classmethod
    def from_action(cls, action: Action):
        """Create instance from Action obj"""
        proto = Prototype(api=action._api, prototype_id=action.prototype_id)
        actions = [action["name"] for action in proto.actions]  # pylint: disable=not-an-iterable
        bundle = Bundle(api=action._api, bundle_id=proto.bundle_id)

        return cls(
            actions=actions,
            parent_name=proto.name,
            parent_type=proto.type,
            bundle_info=f"{bundle.name}_{bundle.version}_{bundle.edition}",
        )


class SetEncoder(json.JSONEncoder):
    """Custom JSONEncoder for set"""

    def default(self, o):
        """Default set encoder implementation"""
        if isinstance(o, set):
            return list(o)
        return json.JSONEncoder.default(self, o)


@dataclass
class ActionsRunReport:
    """Report from actions list"""

    actions: List[ActionRunInfo]
    actions_specs: List[ActionsSpec]

    def make_summary(self) -> str:
        """Make summary report in form of JSON string"""

        def nested_dict():
            """Nested dict helper"""
            return defaultdict(nested_dict)

        report = nested_dict()
        for actions_spec in self.actions_specs:
            for action in actions_spec.actions:
                report[actions_spec.bundle_info][actions_spec.parent_type][actions_spec.parent_name][action] = {
                    "call_count": 0,
                    "expected_statuses": set(),
                    "called_from": set(),
                }
        for action in self.actions:
            action_report = report[action.bundle_info][action.parent_type][action.parent_name][action.action_name]
            action_report["call_count"] += 1
            action_report["expected_statuses"].add(action.expected_status)
            action_report["called_from"].add(action.called_from)
        return json.dumps(report, indent=2, cls=SetEncoder)

    def make_raw_report(self) -> str:
        """Return JSON string with raw list of ActionRunInfo items"""
        return json.dumps([obj.to_dict() for obj in self.actions], indent=2)
