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
Common test steps with actions
"""
from contextlib import contextmanager
from difflib import get_close_matches
from typing import Union

import allure
from adcm_client.base import ObjectNotFound
from adcm_client.objects import Cluster, Service, Host, Task, Component

from .asserts import assert_action_result


def run_cluster_action_and_assert_result(
    cluster: Cluster, action: str, status="success", **kwargs
):
    """
    Run cluster action and assert that status equals to 'status' argument
    """
    with allure.step(
        f"Perform action '{action}' for cluster '{cluster.name}'"
    ), _suggest_action_if_not_exists(cluster, action):
        assert_action_result(
            name=action,
            result=cluster.action(name=action).run(**kwargs).wait(),
            status=status,
        )


def run_service_action_and_assert_result(
    service: Service, action: str, status="success", **kwargs
):
    """
    Run service action and assert that status equals to 'status' argument
    """
    with allure.step(
        f"Perform action '{action}' for service '{service.name}'"
    ), _suggest_action_if_not_exists(service, action):
        assert_action_result(
            name=action,
            result=service.action(name=action).run(**kwargs).wait(),
            status=status,
        )


def run_component_action_and_assert_result(
    component: Component, action: str, status="success", **kwargs
):
    """
    Run component action and assert that status equals to 'status' argument
    """
    with allure.step(
        f"Perform action '{action}' for component '{component.name}'"
    ), _suggest_action_if_not_exists(component, action):
        assert_action_result(
            name=action,
            result=component.action(name=action).run(**kwargs).wait(),
            status=status,
        )


def run_host_action_and_assert_result(
    host: Host, action: str, status="success", **kwargs
):
    """
    Run host action and assert that status equals to 'status' argument
    """
    with allure.step(
        f"Perform action '{action}' for host '{host.fqdn}'"
    ), _suggest_action_if_not_exists(host, action):
        assert_action_result(
            name=action,
            result=host.action(name=action).run(**kwargs).wait(),
            status=status,
        )


@contextmanager
def _suggest_action_if_not_exists(
    obj: Union[Cluster, Service, Host, Component], action
):
    """
    Contextmanager that suggest action if for some reason the required action was not found
    """
    try:
        yield
    except ObjectNotFound as e:
        all_actions = [a.name for a in obj.action_list()]
        suggest_actions = ", ".join(get_close_matches(action, all_actions))
        if suggest_actions:
            raise ObjectNotFound(
                f"No such action {action}. Did you mean: {suggest_actions}?"
            ) from e
        all_actions = ", ".join(all_actions)
        raise ObjectNotFound(
            f"No such action {action}. Possible actions: {all_actions}."
        ) from e


def wait_for_task_and_assert_result(task: Task, status: str):
    """
    Wait for a task to be completed and assert status to be equal to 'status' argument
    """
    # Need to add Action name instead of task_id when links will be provided in ADCM SDK
    with allure.step("Wait for a task to be completed"):
        result = task.wait()
        assert_action_result(result=result, status=status)
