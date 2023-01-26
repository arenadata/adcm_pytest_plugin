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

from typing import Optional

from docker.models.containers import Container

from adcm_pytest_plugin.constants import DEFAULT_IP
from adcm_pytest_plugin.docker.utils import get_network_settings, is_docker


class ADCM:
    def __init__(self, container: Container, ip: str):
        self.container = container

        network_settings = get_network_settings(container)
        ports = network_settings["Ports"]
        self._https = "8443/tcp" in ports

        if ip == DEFAULT_IP and is_docker():
            self._ip = network_settings["IPAddress"]
            self._port = "8000"
            self._secure_port: Optional[str] = "8443"
        else:
            self._ip = ip
            self._port = ports["8000/tcp"][0]["HostPort"]
            self._secure_port: Optional[str] = ports.get("8443/tcp", [{"HostPort": None}])[0]["HostPort"]

    @property
    def url(self):
        """ADCM base URL"""
        return f"{self.protocol}://{self.ip}:{self.port}"

    @property
    def ip(self):
        return self._ip

    @property
    def port(self):
        return self._secure_port if self._https else self._port

    @property
    def protocol(self):
        return "https" if self._https else "http"


class ADCMWithPostgres(ADCM):
    ...
