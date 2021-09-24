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
import os
from argparse import Namespace
from typing import List

import pytest
import requests
from _pytest.config import Config
from docker.utils import parse_repository_tag
from version_utils import rpm

from .fixtures import *  # noqa: F401, F403
from .utils import func_name_to_title, allure_reporter

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


def _get_adcm_tags():
    # remove possible duplicates
    # sort to ensure same order for all xdist workers
    return sorted(list(set(requests.get("https://hub.arenadata.io/v2/adcm/adcm/tags/list").json()["tags"])))


def _filter_adcm_versions_from_tags(adcm_tags: List[str], min_ver: str):
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
    for tag in adcm_tags:
        # make versions with and without dots uniform
        tag = tag.replace(".", "")
        if tag.isdigit():
            # convert to version format
            version = f"{tag[:4]}.{tag[4:6]}.{tag[6:8]}.{tag[8:10]}"
            # filter older versions
            if rpm.compare_versions(version, min_ver[:13]) != -1:
                # since "2021.05.26.12" we have tag with dots for some reason
                if rpm.compare_versions(version, "2021.05.26.12") != -1:
                    yield version
                else:
                    yield version.replace(".", "")


def _get_adcm_new_versions_tags(min_ver):
    tags = _get_adcm_tags()
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


def pytest_sessionfinish():
    """
    Clear custom env variables at the end of all tests
    """
    for var in dict(os.environ):
        if "rep_" in var:
            del os.environ[var]
