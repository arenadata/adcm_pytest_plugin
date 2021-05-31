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
from coreapi.exceptions import ErrorMessage

import allure
from version_utils import rpm
from adcm_client.base import ObjectNotFound
from adcm_client.objects import Cluster, Service, Host, Task, Component, Provider

from .asserts import assert_action_result
from ..plugin import options


def _get_error_text_from_task_logs(task: Task):
    error_text = ""
    for job in task.job_list():
        try:
            for log in job.log_list():
                if log.type == "stdout":
                    error_text += _extract_error_from_ansible_log(log.content)
        except ErrorMessage as log_exception:
            # Multijobs has no logs for parent Job
            # pylint: disable=protected-access
            if log_exception.error._data["code"] == "LOG_NOT_FOUND":
                pass
            else:
                raise log_exception
    return error_text


def _extract_error_from_ansible_log(log: str):
    """
    Extract ansible error message from ansible log

    >>> _extract_error_from_ansible_log("fatal: Some ERROR\\nTASK [api : something] **********")
    'fatal: Some ERROR\\n'
    >>> _extract_error_from_ansible_log(
    ...     "TASK [api : something] **********\\nok: [adcm-cluster-adb-gw0-e330benhwqir]\\n msg: All assertions passed"
    ... )
    ''
    >>> _extract_error_from_ansible_log(
    ...     "TASK [conf]**********\\nfatal: Some \\n multiline\\nERROR\\nNO MORE HOSTS LEFT *********"
    ... )
    'fatal: Some \\n multiline\\nERROR\\n'
    """
    err_start = log.find("fatal:")
    if err_start > -1:
        task_marker = log.find("******", err_start)
        err_end = log.rfind("\n", 0, task_marker) + 1
        return log[err_start:err_end]
    return ""


def _run_action_and_assert_result(
    obj: Union[Cluster, Service, Host, Component, Provider],
    action_name: str,
    expected_status="success",
    timeout=None,
    **kwargs,
):
    """
    Run action and assert that status equals to 'status' argument
    """
    obj_name = obj.name if not isinstance(obj, Host) else obj.fqdn
    with allure.step(
        f"Perform action '{action_name}' for {obj.__class__.__name__} '{obj_name}'"
    ), _suggest_action_if_not_exists(obj, action_name):
        if rpm.compare_versions(obj.adcm_version, "2021.02.04.13") >= 0 and "verbose" not in kwargs:
            kwargs["verbose"] = options.verbose_actions
        task = obj.action(name=action_name).run(**kwargs)
        wait_for_task_and_assert_result(task=task, action_name=action_name, status=expected_status, timeout=timeout)


def run_cluster_action_and_assert_result(cluster: Cluster, action: str, status="success", **kwargs):
    """
    Run cluster action and assert that status equals to 'status' argument
    """
    _run_action_and_assert_result(obj=cluster, action_name=action, expected_status=status, **kwargs)


def run_service_action_and_assert_result(service: Service, action: str, status="success", **kwargs):
    """
    Run service action and assert that status equals to 'status' argument
    """
    _run_action_and_assert_result(obj=service, action_name=action, expected_status=status, **kwargs)


def run_component_action_and_assert_result(component: Component, action: str, status="success", **kwargs):
    """
    Run component action and assert that status equals to 'status' argument
    """
    _run_action_and_assert_result(obj=component, action_name=action, expected_status=status, **kwargs)


def run_host_action_and_assert_result(host: Host, action: str, status="success", **kwargs):
    """
    Run host action and assert that status equals to 'status' argument
    """
    _run_action_and_assert_result(obj=host, action_name=action, expected_status=status, **kwargs)


def run_provider_action_and_assert_result(provider: Provider, action: str, status="success", **kwargs):
    """
    Run provider action and assert that status equals to 'status' argument
    """
    _run_action_and_assert_result(obj=provider, action_name=action, expected_status=status, **kwargs)


@contextmanager
def _suggest_action_if_not_exists(obj: Union[Cluster, Service, Host, Component], action):
    """
    Contextmanager that suggest action if for some reason the required action was not found
    """
    try:
        yield
    except ObjectNotFound as e:
        all_actions = [a.name for a in obj.action_list()]
        suggest_actions = ", ".join(get_close_matches(action, all_actions))
        if suggest_actions:
            raise ObjectNotFound(f"No such action {action}. Did you mean: {suggest_actions}?") from e
        all_actions = ", ".join(all_actions)
        raise ObjectNotFound(f"No such action {action}. Possible actions: {all_actions}.") from e


@allure.step("Wait for a task to be completed")
def wait_for_task_and_assert_result(task: Task, status: str, action_name: str = None, timeout=None):
    """
    Wait for a task to be completed and assert status to be equal to 'status' argument
    If task is expected to succeed bur have failed then ansible error will be added to
    AssertionError message
    """
    result = task.wait(timeout=timeout)
    ansible_error = ""
    if result != status and status == "success":
        ansible_error = _get_error_text_from_task_logs(task)
    assert_action_result(
        name=action_name or task.action().name,
        result=result,
        status=status,
        additional_message=ansible_error,
    )
