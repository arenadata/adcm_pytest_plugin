from typing import Optional

from docker.models.containers import Container

from adcm_pytest_plugin.docker.utils import is_docker, get_network_settings
from adcm_pytest_plugin.constants import DEFAULT_IP


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
