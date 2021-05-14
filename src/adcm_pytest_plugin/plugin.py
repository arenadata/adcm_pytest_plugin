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

# pylint: disable=W0611, W0401, W0614
from argparse import Namespace

import pytest
import requests
from _pytest.config import Config
from version_utils import rpm

from .fixtures import *  # noqa: F401, F403
from .docker_utils import split_tag

options: Namespace = Namespace()


# list of ADCM release tags
ADCM_TAGS = [
    '2021031007',
    '2021030114',
    '2021021506',
    '2020121615',
    '2020081011',
    '2020070611',
    '2020062514',
    '2020031118',
    '2020051315',
    '2020051222',
    '2020022014',
    '2020013015',
    '2020013010',
    '2019121623',
    '2019112016',
    '2019101518',
    '2019100815',
]


def pytest_configure(config: Config):
    """Set global options to plugin property to access to all pytest options outside of fixtures

    Example:
        from adcm_pytest_plugin.plugin import options
        def some_func():
            adcm_image = options.adcm_image
    """
    global options  # pylint: disable=global-statement
    options.__dict__.update(config.option.__dict__)


# pylint: disable=W0621
def pytest_addoption(parser):

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

    parser.addoption(
        "--adcm-repo",
        action="store",
        default="hub.arenadata.io/adcm/adcm",
        help="Name of repo to get ADCM images from "
        " when --adcm-min-version is used "
        "Argument format hub.arenadata.io/adcm/adcm or arenadata/adcm",
    )

    parser.addoption(
        "--adcm-images", nargs="+", help="List of images where to run tests"
    )

    parser.addoption(
        "--nopull", action="store_true", default=False, help="Don't pull image"
    )

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


def pytest_generate_tests(metafunc):
    """
    If any of launch options adcm-min-version or adcm-images is used
    image fixture undergo parametrization with a list of images to be used
    according to used option
    """
    adcm_min_version = metafunc.config.getoption("adcm_min_version")
    adcm_images = metafunc.config.getoption("adcm_images")
    adcm_repo = metafunc.config.getoption("adcm_repo")

    params, ids = parametrized_by_adcm_version(
        adcm_min_version=adcm_min_version, adcm_images=adcm_images, repo=adcm_repo
    )
    if params:
        metafunc.parametrize("image", params, indirect=True, ids=ids)


def parametrized_by_adcm_version(adcm_min_version=None, adcm_images=None, repo="arenadata/adcm"):
    params = None
    ids = None
    if adcm_min_version:
        params = [[repo, tag] for tag in _get_adcm_new_versions_tags(adcm_min_version)]
        ids = list(map(lambda x: x[1] if x[1] is not None else "latest", params))
    elif adcm_images:
        params = [[repo, tag] for repo, tag in map(split_tag, adcm_images)]
        ids = adcm_images
    return params, ids


def _get_adcm_new_versions_tags(min_ver):
    for tag in ADCM_TAGS:
        # convert to version format
        version = "%s.%s.%s.%s" % (tag[:4], tag[4:6], tag[6:8], tag[8:10])
        # filter older versions
        if rpm.compare_versions(version, min_ver[:13]) != -1:
            yield version.replace(".", "")


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """
    There is no default info about test stages execution available in pytest
    This hook is meant to store such info im metadata
    """
    # execute all other hooks to obtain the report object
    outcome = yield
    rep = outcome.get_result()

    # set a report attribute for each phase of a call, which can
    # be "setup", "call", "teardown"

    setattr(item, "rep_" + rep.when, rep)
