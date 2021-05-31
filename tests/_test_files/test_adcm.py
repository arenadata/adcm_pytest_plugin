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
WARNING: this file only for run in 'testdir.runpytest'
"""
import docker
import pytest


@pytest.mark.usefixtures("adcm_fs")
def test_adcm(image):
    """Checking that 'adcm_fs' fixture is running ADCM"""
    repo_name, tag = image
    assert (
        len(docker.from_env().containers.list(filters=dict(ancestor=f"{repo_name}:{tag}"))) == 1
    ), f"Not found running container with '{repo_name}:{tag}' ancestor"
    print((repo_name, tag))  # For teardown testing. This is needed to transfer result of executing fixture to outside.
