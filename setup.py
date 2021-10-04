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
"""Setup plugin"""

from setuptools import setup, find_packages

setup(
    name="adcm_pytest_plugin",
    description="The pytest plugin including a set of common tools for ADCM testing",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    include_package_data=True,
    version="4.9.3",
    # the following makes a plugin available to pytest
    entry_points={"pytest11": ["adcm_pytest_plugin = adcm_pytest_plugin.plugin"]},
    # custom PyPI classifier for pytest plugins
    install_requires=[
        "pytest",
        "docker==5.0.0",
        "adcm_client>=2021.4.15.17",
        "allure-pytest>=2.9.42",
        "requests",
        "version_utils",
        "ifaddr",
        "retry",
        "deprecated",
        "coreapi",
    ],
    classifiers=["Framework :: Pytest"],
)
