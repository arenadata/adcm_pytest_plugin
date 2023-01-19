import os
import string
import tarfile
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from functools import partial
from gzip import compress
from io import BytesIO
from socket import AF_INET, SOCK_STREAM, socket
from tempfile import TemporaryDirectory
from typing import Callable, Generator, Tuple
from uuid import uuid4

import allure
import pytest
from _pytest.fixtures import SubRequest
from docker.models.containers import Container

from adcm_pytest_plugin.docker.commands import dumpdata
from adcm_pytest_plugin.docker.launchers import ADCMLauncher, ADCMWithPostgresLauncher
from adcm_pytest_plugin.docker.utils import get_successful_output
from adcm_pytest_plugin.utils import allure_reporter

# PREPARE

MIN_DOCKER_PORT = 8000
MAX_DOCKER_PORT = 9000
MAX_WORKER_COUNT = 80


class UnableToBind(Exception):
    """Raise when no free port to expose on docker container"""


def _port_is_free(ip, port) -> bool:
    with socket(AF_INET, SOCK_STREAM) as sock:
        return sock.connect_ex((ip, port)) != 0


def _yield_ports(ip) -> Generator[int, None, None]:
    gw_count = os.environ.get("PYTEST_XDIST_WORKER_COUNT", 0)
    if int(gw_count) > MAX_WORKER_COUNT:
        pytest.exit("Expected maximum workers count is {MAX_WORKER_COUNT}.")

    gw_name = os.environ.get("PYTEST_XDIST_WORKER", "gw0")
    gw_number = int(gw_name.strip(string.ascii_letters))

    range_length = (MAX_DOCKER_PORT - MIN_DOCKER_PORT) // MAX_WORKER_COUNT
    offset = MIN_DOCKER_PORT + gw_number * range_length
    port_from: int = 0
    range_start = max(port_from, offset)

    for port in range(range_start, range_start + range_length):
        if _port_is_free(ip, port):
            yield port

    raise UnableToBind("There is no free port for the given worker.")


def get_only_http_port(launcher: ADCMLauncher, *_a, **_kw) -> dict:
    ip = launcher.bind_ip
    return {"ports": {"8000": (ip, next(_yield_ports(ip)))}}


def get_http_and_https_ports(launcher: ADCMLauncher, *_a, **_kw) -> dict:
    ip = launcher.bind_ip
    ports = _yield_ports(ip)
    return {"ports": {"8000": (ip, next(ports)), "8443": (ip, next(ports))}}


def mount_ssl_certs(launcher: ADCMLauncher, run_args, *_a, **_kw) -> dict:
    volumes = run_args.get("volumes", {})
    cert_dir: TemporaryDirectory = launcher.get_step_fact("ssl-certs-directory")
    return {"volumes": {**volumes, cert_dir.name: {"bind": "/adcm/data/conf/ssl", "mode": "ro"}}}


def generate_ssl_certificate_for_adcm(launcher: ADCMLauncher, *_a, **_kw):
    tempdir = TemporaryDirectory()  # pylint: disable=consider-using-with
    launcher.add_step_fact("ssl-certs-directory", tempdir)  # for cleanup

    with allure.step("Generate SSL certificate"):
        cert_dir = tempdir.name
        os.system(
            f"openssl req -x509 -newkey rsa:4096 -keyout {cert_dir}/key.pem -out {cert_dir}/cert.pem"
            ' -days 365 -subj "/C=RU/ST=Moscow/L=Moscow/O=Arenadata Software LLC/OU=Release/CN=ADCM"'
            f' -addext "subjectAltName=DNS:localhost,IP:127.0.0.1,IP:{launcher.adcm.ip}" -nodes'
        )
        file = BytesIO()
        with tarfile.open(mode="w:gz", fileobj=file) as tar:
            tar.add(cert_dir, "")
        file.seek(0)

    with allure.step("Put certificate to ADCM container"):
        launcher.adcm.container.put_archive("/adcm/data/conf/ssl", file.read())

    bundle_path = os.path.join(cert_dir, "bundle.pem")
    os.system(f"cat {cert_dir}/cert.pem {cert_dir}/key.pem > {bundle_path}")
    os.environ["REQUESTS_CA_BUNDLE"] = bundle_path


def cleanup_ssl_certificate_directory(launcher: ADCMLauncher, *_a, **_kw):
    cert_dir: TemporaryDirectory = launcher.get_step_fact("ssl-certs-directory")
    if not cert_dir:
        return

    cert_dir.cleanup()


# GATHER ARTIFACTS


def _collection_required(request: SubRequest) -> bool:
    # If there is no rep_call attribute, presumably test setup failed,
    # or fixture scope is not function. Will collect /adcm/data anyway.
    with suppress(AttributeError):
        if not request.node.rep_call.failed:
            return False
    return True


def _prepare_attach(request: SubRequest, filename: str) -> Tuple[Callable[..., None], dict]:
    reporter = allure_reporter(request.config)
    if reporter:
        return reporter.attach_data, dict(
            name=filename, extension="tgz", uuid=uuid4(), parent_uuid=reporter.get_test(uuid=None).uuid
        )

    return allure.attach, dict(name=filename, extension="tgz")


@contextmanager
def get_directory_from_container(container: Container, directory: str):
    """
    Get directory from a given container as a compressed data stream
    :return: compressed file stream
    """
    bits, _ = container.get_archive(directory)

    with BytesIO() as stream:
        for chunk in bits:
            stream.write(chunk)
        stream.seek(0)
        yield compress(stream.getvalue())


def attach_adcm_data_dir(launcher: ADCMLauncher, request: SubRequest, *_a, **_kw):
    if not _collection_required(request):
        return

    filename = f"ADCM Log {request.node.name}_{time.time()}.tgz"
    attach_method, attach_kwargs = _prepare_attach(request, filename)
    with get_directory_from_container(launcher.adcm.container, "/adcm/data/") as data:
        attach_method(body=data, **attach_kwargs)


def attach_postgres_data_dir(launcher: ADCMWithPostgresLauncher, request: SubRequest, *_a, **_kw):
    if not _collection_required(request):
        return

    dump_file = "/adcm/data/dump.json"
    dumpdata(launcher.adcm, dump_file)
    dump_content = get_successful_output(launcher.adcm.container.exec_run(["cat", dump_file]))[0]

    reporter = allure_reporter(request.config)
    attach_method = (
        partial(reporter.attach_data, uuid=uuid4(), parent_uuid=reporter.get_test(uuid=None).uuid)
        if reporter
        else allure.attach
    )
    attach_method(name="ADCM dumped data", body=dump_content, attachment_type=allure.attachment_type.JSON)


# CLEANUP


def _get_table_names(postgres: Container) -> Iterator[str]:
    return map(
        lambda line: line.split(" | ")[1].strip(),
        filter(
            lambda line: "|" in line,
            # skip uninformative lines
            get_successful_output(postgres.exec_run("psql --username adcm --dbname adcm -c '\\dt'"))[3:],
        ),
    )


@allure.step("Truncate tables in adcm database")
def cleanup_via_truncate(launcher: ADCMWithPostgresLauncher, *_a, **_kw):
    with allure.step("Get a list of tables"):
        # content_type and django_migrations are required, so we won't have to run migrations again
        # messagetemplate is the table that's filled during migrations and we don't expect it to be changed
        #   during test execution
        tables_to_truncate = tuple(
            table
            for table in _get_table_names(launcher.postgres.container)
            if table not in ("django_content_type", "django_migrations", "cm_messagetemplate")
        )

    with allure.step("Clean tables"):
        # will fail if execution failed
        get_successful_output(
            launcher.postgres.container.exec_run(
                "psql --username adcm --dbname adcm -c "
                f"'TRUNCATE {','.join(tables_to_truncate)} RESTART IDENTITY CASCADE;'"
            )
        )


@allure.step("Drop all tables in adcm database")
def cleanup_via_tables_drop(launcher: ADCMWithPostgresLauncher, *_a, **_kw):
    with allure.step("Get a list of tables"):
        tables_to_delete = _get_table_names(launcher.postgres.container)

    with allure.step("Drop tables"):
        # will fail if execution failed
        get_successful_output(
            launcher.postgres.container.exec_run(
                f"psql --username adcm --dbname adcm -c 'DROP TABLE IF EXISTS {','.join(tables_to_delete)} CASCADE;'"
            )
        )
