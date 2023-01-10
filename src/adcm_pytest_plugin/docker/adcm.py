from typing import Optional, Tuple

import allure
from docker.models.containers import Container

from adcm_pytest_plugin.docker.utils import is_docker
from adcm_pytest_plugin.constants import DEFAULT_IP


class ADCM:
    def __init__(self, container: Container, ip: str, https: bool):
        self.container = container
        self._https = https

        network_settings = container.client.api.inspect_container(container.id)["NetworkSettings"]
        if ip == DEFAULT_IP and is_docker():
            self._ip = network_settings["IPAddress"]
            self._port = "8000"
            self._secure_port: Optional[str] = "8443"
        else:
            self._ip = ip
            # it's some bold assumption, but should work
            self._port = network_settings["Ports"]["8000/tcp"][0]["HostPort"]
            # TODO no clue if it's correct
            self._secure_port: Optional[str] = network_settings["Ports"].get("8443/tcp", [{"HostPort": None}])[0][
                "HostPort"
            ]

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

    @allure.step("Upgrade ADCM to {target}")
    def upgrade(self, target: Tuple[str, str]) -> None:
        """Stop old ADCM container and start new container with /adcm/data mounted"""
        # TODO rework
        # image, tag = target
        # assert (
        #     self.container_config.volumes
        # ), "There is no volume to move data. Make sure you are using the correct ADCM fixture for upgrade"
        # volume_name = list(self.container_config.volumes.keys()).pop()
        # volume = self.container_config.volumes.get(volume_name)
        # with allure.step("Copy /adcm/data to the folder attached by volume"):
        #     self.container.exec_run(f"sh -c 'cp -a /adcm/data/* {volume['bind']}'")
        # with allure.step("Update ADCM container config"):
        #     self.container_config.image = image
        #     self.container_config.tag = tag
        #     volume.update({"bind": "/adcm/data"})
        # with allure.step("Stop old ADCM container"):
        #     self.stop()
        # with allure.step("Start newer ADCM container"):
        #     self.container, self.container_config = self.docker_wrapper.run_adcm_container_from_config(
        #         self.container_config
        #     )


class ADCMWithPostgres(ADCM):
    @allure.step("Upgrade ADCM to {target}")
    def upgrade(self, target: Tuple[str, str]) -> None:
        # TODO implement upgrade without volumes
        raise NotImplemented
