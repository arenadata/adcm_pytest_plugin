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
from datetime import datetime

import docker
import pytest

test_start_time = datetime.now().timestamp()


def test_image(image):
    """
    Check that 'image' fixture creates ADCM image
    """
    repo_name, tag = image
    assert repo_name == "local/adcminit"
    assert isinstance(tag, str)
    assert len(tag) == 10

    client = docker.from_env()
    created_image_list = []
    for docker_image in client.images.list(name="local/adcminit"):
        for event in docker_image.history():
            if event["Tags"] and "local/adcminit" in event["Tags"][0]:
                if test_start_time < event["Created"]:
                    created_image_list.append({event["Tags"][0]: str(datetime.fromtimestamp(event["Created"]))})
    assert len(created_image_list) != 0, "Image not created"
    assert len(created_image_list) == 1, "More than 1 image created"
    # For teardown testing. This is needed to transfer result of executing fixture to outside.
    pytest.test_retval = repo_name, tag
