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

"""Main module of plugin with options and hooks"""
# pylint: disable=wildcard-import,unused-wildcard-import
import json
import os
import pathlib
import shutil
from argparse import Namespace
from typing import Iterator, List

import pytest
import requests
from _pytest.config import Config
from docker.utils import parse_repository_tag
from version_utils import rpm

from .fixtures import *  # noqa: F401, F403
from .objects.actions import ActionRunInfo, ActionsRunReport, ActionsSpec
from .params import *  # noqa: F401, F403
from .utils import allure_reporter, func_name_to_title

options: Namespace = Namespace()
_PHASE_RESULT_VAR_NAME_TEMPLATE = "rep_{phase}_passed"


def pytest_configure(config: Config):
    """Set global options to plugin property to access to all pytest options outside of fixtures

    Example:
        from adcm_pytest_plugin.plugin import options
        def some_func():
            adcm_image = options.adcm_image
    """
    global options  # pylint: disable=global-statement,invalid-name,global-variable-not-assigned
    options.__dict__.update(config.option.__dict__)
    if config.option.actions_report_dir:
        pytest.action_run_storage = []
        pytest.actions_spec_storage = {}
        if not os.getenv("PYTEST_XDIST_WORKER"):
            try:
                shutil.rmtree(_get_actions_dir(config))
            except FileNotFoundError:
                pass


def pytest_addoption(parser):
    """Add plugin CLI options"""

    parser.addoption(
        "--staticimage",
        action="store",
        default=None,
        help="Use pre-initialised ADCM image. "
        "If image doesn't exist then it will be created ones "
        "and can be reused in future test runs. "
        "Useful for tests development. You will save about 40 second on ADCM initialisation "
        "Ex: arenadata/adcm:test or some_repo/some_image:some_tag",
    )

    parser.addoption(
        "--dontstop",
        action="store_true",
        default=False,
        help="Keep ADCM containers running after tests are finished",
    )

    parser.addoption(
        "--adcm-image",
        action="store",
        default=None,
        help="ADCM image to use as base image in tests. "
        "Ex: arenadata/adcm:2021031007, or arenadata/adcm then tag will be 'latest'",
    )

    parser.addoption(
        "--adcm-min-version",
        action="store",
        default=None,
        help="In this mode test will run on all ADCM release images "
        " that are newer that min version. "
        "Argument format 2020.01.30.15-c4c8b2a or 2020.01.30.15",
    )

    parser.addoption("--adcm-images", nargs="+", help="List of images where to run tests")

    parser.addoption("--nopull", action="store_true", default=False, help="Don't pull image")

    parser.addoption(
        "--remote-executor-host",
        action="store",
        default=None,
        help="This option will be ignored if remote-docker option is passed. "
        "This option is used to initialise ADCM API with external IP "
        "to allow incoming connections from any remote executor (ex. Selenoid). "
        "Test will fail if remote host is unreachable",
    )

    parser.addoption(
        "--remote-docker",
        action="store",
        default=None,
        help="This option will ignore remote-executor-host option "
        "and attach ADCM Api to docker host by default. "
        "This option is used to start ADCM instances on the remote host. "
        "Docker daemon should be running and be available with provided ip:port "
        "Ex: '192.168.1.1:2375'",
    )

    parser.addoption(
        "--verbose-actions",
        action="store_true",
        default=False,
        help="Run actions with 'verbose' checkbox selected. "
        "Applied only to action calls over adcm_client."
        "Does not affect UI action calls in tests",
    )

    parser.addoption(
        "--actions-report-dir",
        action="store",
        type=pathlib.Path,
        default=None,
        help="Enable collection of the called actions report to provided dir",
    )


def pytest_generate_tests(metafunc):
    """
    If any of launch options adcm-min-version or adcm-images is used
    image fixture undergo parametrization with a list of images to be used
    according to used option
    """
    adcm_min_version = metafunc.config.getoption("adcm_min_version")
    adcm_images = metafunc.config.getoption("adcm_images")

    params, ids = parametrized_by_adcm_version(adcm_min_version=adcm_min_version, adcm_images=adcm_images)
    if params:
        metafunc.parametrize("image", params, indirect=True, ids=ids)


def parametrized_by_adcm_version(adcm_min_version=None, adcm_images=None):
    """Return params with range from ADCM min version to current ADCM version"""
    params = None
    ids = None
    if adcm_min_version:
        repo = "hub.arenadata.io/adcm/adcm"
        params = [[repo, tag] for tag in _get_adcm_new_versions_tags(adcm_min_version)]
        ids = list(map(lambda x: x[1] if x[1] is not None else "latest", params))
    elif adcm_images:
        params = [[repo, tag] for repo, tag in map(parse_repository_tag, adcm_images)]
        ids = adcm_images
    return params, ids


def _get_unique_sorted_tags(tags: List[str]) -> List[str]:
    """
    Get unique tags from list as sorted list
        (20212012 and 2021.20.12 are considered the same and only one of them (without dots) is returned)

    >>> this = _get_unique_sorted_tags
    >>> this(['20201210', '20190610', '2020.11.10'])
    ['20190610', '2020.11.10', '20201210']
    >>> this(['2020.12.10', '20190610', '20201110'])
    ['20190610', '20201110', '2020.12.10']
    >>> this(['20201210', '20190610', '20201110', '2019.05.30', '2020.11.10', '2019.10.16'])
    ['2019.05.30', '20190610', '2019.10.16', '20201110', '20201210']
    >>> this(['20201210', '20190610', '2020.11.10', '20201110', '2019.05.30',  '2019.10.16'])
    ['2019.05.30', '20190610', '2019.10.16', '20201110', '20201210']
    """

    unique_tags = {tag for tag in tags if "." not in tag}
    # we have duplicates for some versions where one element is with dots and another without
    unique_tags |= {tag for tag in tags if tag not in unique_tags and tag.replace(".", "") not in unique_tags}
    return sorted(unique_tags, key=lambda x: x.replace(".", ""))


def _get_adcm_tags() -> List[str]:
    """Return unsorted list of ADCM tags from hub.arenadata.io (newest tag is last)"""
    return requests.get("https://hub.arenadata.io/v2/adcm/adcm/tags/list").json()["tags"]


def _filter_adcm_versions_from_tags(adcm_tags: List[str], min_ver: str) -> Iterator[str]:
    """
    >>> this = _filter_adcm_versions_from_tags
    >>> list(this(["2021021506","2021030114","2021031007","latest","2021.05.26.12","2021.06.17.06"], "2019.03.01.14"))
    ['2021021506', '2021030114', '2021031007', '2021.05.26.12', '2021.06.17.06']
    >>> list(this(["2021021506","2021030114","2021031007","latest","2021.05.26.12","2021.06.17.06"], "2021.03.01.14"))
    ['2021030114', '2021031007', '2021.05.26.12', '2021.06.17.06']
    >>> list(this(["2021021506","2021030114","2021031007","latest","2021.05.26.12","2021.06.17.06"], "2021.05.26.12"))
    ['2021.05.26.12', '2021.06.17.06']
    >>> list(this(["2021021506","2021030114","2021031007","latest","2021.05.26.12","2021.06.17.06"], "2022.05.26.12"))
    []
    """
    return filter(
        lambda x: (tag := x.replace(".", ""))
        and (tag.isdigit())  # noqa: W503
        and (rpm.compare_versions(f"{tag[:4]}.{tag[4:6]}.{tag[6:8]}.{tag[8:10]}", min_ver[:13]) != -1),  # noqa: W503
        adcm_tags,
    )


def _get_adcm_new_versions_tags(min_ver: str):
    """Get ADCM tags greater or equal than min_ver"""
    # remove possible duplicates
    # sort to ensure same order for all xdist workers
    tags = _get_unique_sorted_tags(_get_adcm_tags())
    for version in _filter_adcm_versions_from_tags(tags, min_ver):
        yield version


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_protocol():
    """
    Remove env vars before run test
    """
    possible_phases = ("setup", "call", "teardown")
    # Xdist left env vars on worker before run new test on it. Clean possible env vars
    for phase in possible_phases:
        phase_var_name = _PHASE_RESULT_VAR_NAME_TEMPLATE.format(phase=phase)
        os.environ.pop(phase_var_name, None)
    yield


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """
    There is no default info about test stages execution available in pytest
    This hook is meant to store such info im metadata
    """
    if hasattr(item, "callspec") and call.when == "setup":
        reporter = allure_reporter(item.config)
        if reporter:
            latest_test = reporter.get_test(None)
            latest_test.name = func_name_to_title(latest_test.name)

    # execute all other hooks to obtain the report object
    outcome = yield
    rep = outcome.get_result()

    # set a report attribute for each phase of a call, which can
    # be "setup", "call", "teardown"
    os.environ[_PHASE_RESULT_VAR_NAME_TEMPLATE.format(phase=rep.when)] = str(rep.passed)
    setattr(item, "rep_" + rep.when, rep)


def _get_actions_dir(config):
    return config.option.actions_report_dir


def pytest_sessionfinish(session):
    """
    Clear custom env variables at the end of all tests
    Create files with raw actions call data
    """
    for var in dict(os.environ):
        if "rep_" in var:
            del os.environ[var]

    if session.config.option.actions_report_dir:
        actions_report_dir = _get_actions_dir(session.config)
        actions_report_dir.mkdir(parents=True, exist_ok=True)
        with open(
            os.path.join(actions_report_dir, f"{os.getenv('PYTEST_XDIST_WORKER', 'master')}_run.json"),
            "w",
            encoding="utf-8",
        ) as file:
            file.write(json.dumps([obj.to_dict() for obj in pytest.action_run_storage], indent=2))
        del pytest.action_run_storage
        with open(
            os.path.join(actions_report_dir, f"{os.getenv('PYTEST_XDIST_WORKER', 'master')}_spec.json"),
            "w",
            encoding="utf-8",
        ) as file:
            file.write(
                json.dumps({key: value.to_dict() for key, value in pytest.actions_spec_storage.items()}, indent=2)
            )
        del pytest.actions_spec_storage


def pytest_unconfigure(config: Config):
    """Create actions call report"""
    if not os.getenv("PYTEST_XDIST_WORKER") and config.option.actions_report_dir:
        summary_file = "summary.json"
        common_actions_call_list = []
        common_actions_spec = {}
        actions_report_dir = _get_actions_dir(config)
        for filename in os.listdir(actions_report_dir):
            with open(os.path.join(actions_report_dir, filename), "r", encoding="utf-8") as file:
                content = file.read()
            if "run" in filename:
                common_actions_call_list.extend([ActionRunInfo.from_dict(obj) for obj in json.loads(content)])
            if "spec" in filename:
                for uniq_id, actions_spec_dict in json.loads(content).items():
                    actions_spec = ActionsSpec.from_dict(actions_spec_dict)
                    common_actions_spec[uniq_id] = actions_spec
            os.remove(os.path.join(actions_report_dir, filename))
        with open(
            os.path.join(actions_report_dir, summary_file),
            "w",
            encoding="utf-8",
        ) as file:
            file.write(
                ActionsRunReport(
                    actions=common_actions_call_list, actions_specs=common_actions_spec.values()
                ).make_summary()
            )
