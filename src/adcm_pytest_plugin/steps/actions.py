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
import re
from contextlib import contextmanager
from difflib import get_close_matches
from typing import Union
from coreapi.exceptions import ErrorMessage

import allure
from version_utils import rpm
from adcm_client.base import ObjectNotFound
from adcm_client.objects import Cluster, Service, Host, Task, Component, Provider

from .asserts import assert_action_result
from ..exceptions.adcm import ADCMError
from ..plugin import options


def _get_error_text_from_task_logs(task: Task):
    """
    Extract error message from task logs

    >>> test_task = lambda: None
    >>> test_job = lambda: None
    >>> stdout_log = lambda: None
    >>> stdout_log.type = "stdout"
    >>> stderr_log = lambda: None
    >>> stderr_log.type = "stderr"
    >>> test_job.log_list = lambda: [stderr_log, stdout_log]
    >>> test_task.job_list = lambda status: [test_job]
    >>> stdout_log.content = "fatal: Some ERROR\\nTASK [api : something] **********\\n"
    >>> stderr_log.content = "ERROR! the role 'monitoring' was not found\\n"
    >>> _get_error_text_from_task_logs(test_task)
    "ERROR! the role 'monitoring' was not found"
    >>> stdout_log.content = "fatal: Some ERROR\\nTASK [api : something] **********\\n"
    >>> stderr_log.content = "[WARNING] conditional statements should not include jinja2 templating\\n"
    >>> _get_error_text_from_task_logs(test_task)
    'fatal: Some ERROR'
    >>> error_obj = lambda: None
    >>> error_obj._data = dict()
    >>> error_obj._data["code"] = "LOG_NOT_FOUND"
    >>> multijob_logs_error = ErrorMessage(error=error_obj)
    >>> test_job.log_list = lambda: (_ for _ in ()).throw(multijob_logs_error)
    >>> _get_error_text_from_task_logs(test_task)
    ''
    """

    error_text = ""
    for job in task.job_list(status="failed"):
        try:
            for log in job.log_list():
                if log.type == "stderr":
                    if extracted_error := _extract_error_from_ansible_stderr(log.content):
                        error_text += extracted_error
                        break
                if log.type == "stdout":
                    error_text += _extract_error_from_ansible_stdout(log.content)
        except ErrorMessage as log_exception:
            # Multijobs has no logs for parent Job
            # pylint: disable=protected-access
            if log_exception.error._data["code"] == "LOG_NOT_FOUND":
                pass
            else:
                raise log_exception
    return error_text


def _extract_error_from_ansible_stderr(stderr: str):
    """
    Extract ansible error message from ansible stderr log

    >>> this = _extract_error_from_ansible_stderr
    >>> this('''
    ... [WARNING]: conditional statements should not include jinja2 templating
    ... [DEPRECATION WARNING]: Use errors="ignore" instead of skip. This feature will
    ... ''')
    ''
    >>> this('''
    ... [WARNING]: conditional statements should not include jinja2 templating
    ... ERROR! the role 'monitoring' was not found
    ...  include_role:
    ...    name: monitoring
    ...          ^ here
    ... [DEPRECATION WARNING]: Use errors="ignore" instead of skip. This feature will
    ... ''')
    "ERROR! the role \'monitoring\' was not found\\n include_role:\\n   name: monitoring\\n         ^ here\\n"
    >>> this('''
    ... [WARNING]: conditional statements should not include jinja2 templating
    ... ERROR! the role 'monitoring' was not found
    ...  include_role:
    ...    name: monitoring
    ...          ^ here
    ... ''')
    "ERROR! the role \'monitoring\' was not found\\n include_role:\\n   name: monitoring\\n         ^ here"
    """
    err_start = stderr.find("ERROR!")
    if err_start > -1:
        err_end = stderr.rfind("[", err_start)
        return stderr[err_start:err_end]
    return ""


def _extract_error_from_ansible_stdout(log: str):
    """
    Extract ansible error message from ansible stdout log
    >>> this = _extract_error_from_ansible_stdout
    >>> this('''
    ... TASK [first failed task] ***
    ... datetime *****
    ... fatal: [fqdn]: FAILED! => changed=false
    ... msg: 2
    ...
    ... TASK [failed task] ***
    ... datetime *****
    ... fatal: [fqdn]: FAILED! => changed=false
    ... msg: 1
    ...
    ... TASK [api : something] ***
    ... datetime ***
    ... ok: [fqdn]
    ... msg: All assertions passed"
    ... NO MORE HOSTS LEFT *********
    ... PLAY RECAP *********************************************************************
    ... host-1 : ok=7    changed=0    failed=0    skipped=3    rescued=0    ignored=0
    ... host-2 : ok=7    changed=0    failed=0    skipped=3    rescued=0    ignored=0
    ... host-3 : ok=20   changed=0    failed=2    skipped=5    rescued=0    ignored=0
    ... ''')
    'TASK [first failed task] ***\\ndatetime *****\\nfatal: [fqdn]: FAILED! => changed=false\\nmsg: 2\\n'
    >>> this('''
    ... TASK [first failed task] ***
    ... datetime *****
    ... fatal: [fqdn]: FAILED! => changed=false
    ... msg: 2
    ...
    ... TASK [failed task] ***
    ... datetime *****
    ... fatal: [fqdn]: FAILED! => changed=false
    ... msg: 1
    ...
    ... TASK [api : something] ***
    ... datetime ***
    ... ok: [fqdn]
    ... msg: All assertions passed"
    ... NO MORE HOSTS LEFT *********
    ... PLAY RECAP *********************************************************************
    ... host-1 : ok=7    changed=0    failed=0    skipped=3    rescued=1    ignored=0
    ... host-2 : ok=7    changed=0    failed=0    skipped=3    rescued=0    ignored=0
    ... host-3 : ok=20   changed=0    failed=2    skipped=5    rescued=0    ignored=0
    ... ''')
    'TASK [failed task] ***\\ndatetime *****\\nfatal: [fqdn]: FAILED! => changed=false\\nmsg: 1\\n'
    """
    rescued = _get_rescued_count_from_log(log)
    failed_tasks = _get_all_fatal_from_ansible_stdout(log)
    return failed_tasks[rescued]


def _get_all_fatal_from_ansible_stdout(log: str):
    """
    Get all TASKS with fatal status from ansible log
    >>> this = _get_all_fatal_from_ansible_stdout
    >>> this("fatal: Some ERROR\\nTASK [api : something] **********")
    ['fatal: Some ERROR']
    >>> this('''
    ... TASK [api : something] ***
    ... datetime **********
    ... ok: [adcm-cluster-adb-gw0-e330benhwqir]
    ... msg: All assertions passed"
    ... ''')
    []
    >>> this('''
    ... TASK [api : something] ***
    ... datetime **********
    ... ok: [adcm-cluster-adb-gw0-e330benhwqir]
    ... msg: All assertions passed"
    ...
    ... TASK [failed task] ***
    ... datetime *********
    ... fatal: [fqdn]: FAILED! => changed=false
    ... msg: Assertion failed
    ... NO MORE HOSTS LEFT *********
    ... ''')
    ['TASK [failed task] ***\\ndatetime *********\\nfatal: [fqdn]: FAILED! => changed=false\\nmsg: Assertion failed']
    >>> this('''
    ... TASK [ignoring failed task] ***
    ... datetime *********
    ... fatal: [fqdn]: FAILED! => changed=false
    ... msg: Assertion failed
    ... ...ignoring
    ... NO MORE HOSTS LEFT *********
    ... ''')
    []
    >>> this('''
    ... TASK [ignoring failed task] ***
    ... datetime *********
    ... fatal: [fqdn]: FAILED! => changed=false
    ... msg: Assertion failed
    ... ...ignoring
    ...
    ... TASK [failed task] ***
    ... datetime *********
    ... fatal: [fqdn]: FAILED! => changed=false
    ... msg: captured
    ...
    ... TASK [api : something] ***
    ... datetime **********
    ... ok: [adcm-cluster-adb-gw0-e330benhwqir]
    ... msg: All assertions passed"
    ... NO MORE HOSTS LEFT *********
    ... ''')
    ['TASK [failed task] ***\\ndatetime *********\\nfatal: [fqdn]: FAILED! => changed=false\\nmsg: captured\\n']
    >>> this('''
    ... TASK [first failed task] ***
    ... datetime *****
    ... fatal: [fqdn]: FAILED! => changed=false
    ... msg: 2
    ...
    ... TASK [failed task] ***
    ... datetime *****
    ... fatal: [fqdn]: FAILED! => changed=false
    ... msg: 1
    ...
    ... TASK [api : something] ***
    ... datetime ***
    ... ok: [fqdn]
    ... msg: All assertions passed"
    ... NO MORE HOSTS LEFT *********
    ... ''')
    ['TASK [first failed task] ***\\ndatetime *****\\nfatal: [fqdn]: FAILED! => changed=false\\nmsg: 2\\n', \
'TASK [failed task] ***\\ndatetime *****\\nfatal: [fqdn]: FAILED! => changed=false\\nmsg: 1\\n']
    """
    fatal_tasks = []
    err_start = -2
    while (err_start := log.find("fatal:", err_start + 2)) > -1:
        task_name_start = log.rfind("TASK [", 0, err_start)
        task_marker = log.find("***", err_start)
        err_end = log.rfind("\n", 0, task_marker)
        error_text = log[task_name_start if task_name_start > -1 else err_start : err_end]
        if "...ignoring" not in error_text:
            fatal_tasks.append(error_text)
    return fatal_tasks


def _get_rescued_count_from_log(log: str):
    """
    Get overall count of rescued tasks
    >>> this = _get_rescued_count_from_log
    >>> this('''
    ... PLAY RECAP *********************************************************************
    ... host-1 : ok=7    changed=0    failed=0    skipped=3    rescued=0    ignored=0
    ... host-2 : ok=7    changed=0    failed=0    skipped=3    rescued=0    ignored=0
    ... host-3 : ok=20   changed=0    failed=2    skipped=5    rescued=0    ignored=0
    ... ''')
    0
    >>> this('''
    ... PLAY RECAP *********************************************************************
    ... host-1 : ok=7    changed=0    failed=0    skipped=3    rescued=1    ignored=0
    ... host-2 : ok=7    changed=0    failed=0    skipped=3    rescued=1    ignored=0
    ... host-3 : ok=20   changed=0    failed=2    skipped=5    rescued=0    ignored=0
    ... ''')
    2
    >>> this('''
    ... PLAY RECAP *********************************************************************
    ... host-1 : ok=7    changed=0    failed=0    skipped=3    rescued=0    ignored=0
    ... host-2 : ok=7    changed=0    failed=0    skipped=3    rescued=0    ignored=0
    ... host-3 : ok=20   changed=0    failed=2    skipped=5    rescued=5    ignored=0
    ... ''')
    5
    """
    return sum(map(int, re.findall(r"rescued=(\d+)", log)))


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
            kwargs["verbose"] = options.verbose_actions  # pylint: disable=no-member
        obj.reread()
        try:
            task = obj.action(name=action_name).run(**kwargs)
        except ErrorMessage as err:
            ADCMError.raise_if_suitable(err.error.title)
            raise
        wait_for_task_and_assert_result(task=task, action_name=action_name, status=expected_status, timeout=timeout)
        return task


def run_cluster_action_and_assert_result(cluster: Cluster, action: str, status="success", **kwargs):
    """
    Run cluster action and assert that status equals to 'status' argument
    """
    return _run_action_and_assert_result(obj=cluster, action_name=action, expected_status=status, **kwargs)


def run_service_action_and_assert_result(service: Service, action: str, status="success", **kwargs):
    """
    Run service action and assert that status equals to 'status' argument
    """
    return _run_action_and_assert_result(obj=service, action_name=action, expected_status=status, **kwargs)


def run_component_action_and_assert_result(component: Component, action: str, status="success", **kwargs):
    """
    Run component action and assert that status equals to 'status' argument
    """
    return _run_action_and_assert_result(obj=component, action_name=action, expected_status=status, **kwargs)


def run_host_action_and_assert_result(host: Host, action: str, status="success", **kwargs):
    """
    Run host action and assert that status equals to 'status' argument
    """
    return _run_action_and_assert_result(obj=host, action_name=action, expected_status=status, **kwargs)


def run_provider_action_and_assert_result(provider: Provider, action: str, status="success", **kwargs):
    """
    Run provider action and assert that status equals to 'status' argument
    """
    return _run_action_and_assert_result(obj=provider, action_name=action, expected_status=status, **kwargs)


@contextmanager
def _suggest_action_if_not_exists(obj: Union[Cluster, Service, Host, Component], action):
    """
    Contextmanager that suggest action if for some reason the required action was not found
    """
    try:
        yield
    except ObjectNotFound as err:
        all_actions = [a.name for a in obj.action_list()]
        suggest_actions = ", ".join(get_close_matches(action, all_actions))
        if suggest_actions:
            raise ObjectNotFound(f"No such action {action}. Did you mean: {suggest_actions}?") from err
        all_actions = ", ".join(all_actions)
        raise AssertionError(
            f"No such action {action}. {obj.__class__.__name__} state: {obj.state}. Possible actions: {all_actions}"
        ) from err


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
