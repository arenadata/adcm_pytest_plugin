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
import warnings
from collections import defaultdict
from dataclasses import asdict, dataclass, fields
from typing import List

from adcm_client.objects import Action, Bundle, Prototype


def _get_bundle_id(bundle: Bundle):
    return f"{bundle.name}_{bundle.version.split('-')[0]}_{bundle.edition}"


def _make_parent_name(prototype: Prototype):
    return f"{prototype.name}.{prototype.display_name}"


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
        return asdict(self)

    @classmethod
    def from_dict(cls, source_dict: dict):
        """Recreate instance from json string"""
        return cls(**{key.name: source_dict[key.name] for key in fields(cls)})

    # pylint: disable=protected-access
    @classmethod
    def from_action(cls, action: Action, expected_status: str = "Undefined"):
        """Create instance from Action obj"""
        proto = Prototype(api=action._api, prototype_id=action.prototype_id)
        bundle = Bundle(api=action._api, bundle_id=proto.bundle_id)
        return cls(
            action_name=action.name,
            expected_status=expected_status,
            parent_name=_make_parent_name(proto),
            parent_type=proto.type,
            bundle_info=_get_bundle_id(bundle),
            called_from=os.getenv("PYTEST_CURRENT_TEST", "Undefined"),
        )


@dataclass
class ActionsSpec:
    """Info about all actions from prototype
    Is used to compare actually called actions with the full actions list"""

    actions: List[str]
    parent_name: str
    parent_type: str
    bundle_info: str

    def to_dict(self):
        """Convert object to dict"""
        return asdict(self)

    @property
    def uniq_id(self):
        """Get identifier"""
        return f"{self.bundle_info}_{self.parent_type}_{self.parent_name}"

    @classmethod
    def from_dict(cls, source_dict: dict):
        """Recreate instance from json string"""
        return cls(**{key.name: source_dict[key.name] for key in fields(cls)})

    # pylint: disable=protected-access
    @classmethod
    def from_action(cls, action: Action):
        """Create instance from Action obj"""
        proto = Prototype(api=action._api, prototype_id=action.prototype_id)
        actions = [action["name"] for action in proto.actions]  # pylint: disable=not-an-iterable
        bundle = Bundle(api=action._api, bundle_id=proto.bundle_id)

        return cls(
            actions=actions,
            parent_name=_make_parent_name(proto),
            parent_type=proto.type,
            bundle_info=_get_bundle_id(bundle),
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
            """
            Recursive defaultdict declaration.
            Resulting object will be defaultdict with arbitrary depth
            Ex.
            demo = nested_dict()
            demo["new_key_level_1"]["new_key_level_2"]["new_key_level_3"] = "value"
            demo["newer_key_level_1"]["newer_key_level_2"] = "yet another value"
            """
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
            if isinstance(action_report, defaultdict):
                warnings.warn(
                    f"No spec found for action {action.action_name} on {action.parent_type} {action.action_name}"
                )
                action_report = {
                    "call_count": 0,
                    "expected_statuses": set(),
                    "called_from": set(),
                }
            action_report["call_count"] += 1
            action_report["expected_statuses"].add(action.expected_status)
            action_report["called_from"].add(action.called_from)
        return json.dumps(report, indent=2, cls=SetEncoder)

    def make_raw_report(self) -> str:
        """Return JSON string with raw list of ActionRunInfo items"""
        return json.dumps([obj.to_dict() for obj in self.actions], indent=2)
