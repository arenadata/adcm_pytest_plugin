# ADCM Pytest Plugin

## Overview

The `pytest` plugin which includes a set of common tools for ADCM tests.

- [Requirements](#requirements)
- [Installation](#installation)
- [Fixtures](#fixtures)
- [Functions and methods](#functions-and-methods)
- [Basic usage](#basic-usage)
- [Command line options](#command-line-options)
- [Writing tests for plugin](#writing-tests-for-plugin)
- [How to run unit tests for plugin](#how-to-run-unit-tests-for-plugin)
- [Pre-commit hook](#pre-commit-hook)


## Requirements

- `python (3.7+)`
- `pip`

## Installation

```shell
pip install adcm_pytest_plugin
```

## Fixtures

### A word about naming convention

The most of the fixture names introduced by this plugin has a suffix which indicates fixture scope. The following list
of suffixes are in use:

- `_fs` - function scope
- `_ms` - module scope
- `_ss` - session scope

Here in after the name of any fixture used without scope suffix unless stated.

E.g. `adcm` which expands to:

- `adcm_fs`
- `adcm_ms`
- `adcm_ss`

### List of fixtures

- `image`<sup>session scope only</sup> - creates initialized ADCM image for further usage in tests
- `cmd_opts`<sup>session scope only</sup> - fixture aimed to access values of cmd_line options
- `adcm` - returns instance of ADCM wrapper (ADCM API and Docker container)
- `sdk_client` - returns ADCMClient instance bounded to ADCM instance
- `adcm_api_credentials` - returns dict with default ADCM credentials

## Functions and methods

`utils.py` contains a lot of methods useful for testing. See docstrings for more info.

## Basic usage

Assume running from `adcm_test`.

> `conftest.py`

```python
import os

import pytest

from adcm_pytest_plugin.utils import random_string

from adcm_client.objects import Bundle, Cluster, ADCMClient


@pytest.fixture()
def dummy_bundle(sdk_client_fs: ADCMClient) -> Bundle:
    """
    Uploads bundle from dummy_bundle folder 
    """
    bundle = sdk_client_fs.upload_from_fs(
        os.path.dirname(os.path.abspath(__file__)) + "/dummy_bundle"
    )

    return bundle


@pytest.fixture()
def dummy_cluster(dummy_bundle: Bundle) -> Cluster:
    """
    Initialize cluster (based on the cluster prototype)
    """

    cluster = dummy_bundle.cluster_prototype().cluster_create(
        name=f"test_cluster_{random_string()}"
    )

    return cluster

```

> `dummy_bundle/config.yaml` see [ADCM docs](https://docs.arenadata.io/adcm/sdk/config.html) for details

```yaml
---
- name: dummy_cluster
  type: cluster
  version: '1.0'
  config:
    - name: some_boolean_param
      type: boolean
      required: true
      default: false
  actions:
    dummy_job:
      description: "Will fail if config param is false"
      script: cluster_action.yaml
      script_type: ansible
      type: job
      states:
        available:
          - created
```

> `dummy_bundle/cluster_action.yaml`

```yaml
---
- name: fail_if_some_boolean_param_is_false
  hosts: localhost
  tasks:
    - name: Assert bool value
      assert:
        that:
          - cluster.config.some_boolean_param == true
```

> `test_cluster_action.py`

```python
from adcm_pytest_plugin.steps.actions import (
    run_cluster_action_and_assert_result,
)
from adcm_client.objects import Cluster


def test_cluster_action(dummy_cluster: Cluster):
    """Test cluster action run and result"""

    run_cluster_action_and_assert_result(
        cluster=dummy_cluster, action="dummy_job", status="failed"
    )

    dummy_cluster.config_set_diff({"some_boolean_param": True})

    run_cluster_action_and_assert_result(
        cluster=dummy_cluster, action="dummy_job", status="success"
    )

```

**Then** run `pytest` with command line arguments described [below](#command-line-options).

## Command line options

List of available options:

- ADCM image options
    - [`--staticimage`](#--staticimage)
    - [`--dontstop`](#--dontstop)
    - [`--adcm-image`](#--adcm-image)
    - [`--adcm-images`](#--adcm-images)
    - [`--adcm-min-version`](#--adcm-min-version)
    - [`--nopull`](#--nopull)
- Misc
    - [`--remote-executor-host`](#--remote-executor-host)
    - [`--remote-docker`](#--remote-docker)
    - [`--verbose-actions`](#--verbose-actions)

---

### ADCM image options

#### `--staticimage`

> Use single ADCM docker image instead of initializing new one at the test session start

Property | Value
---: | ---
value | `any valid docker image name`
default | `none`
example | `--staticimage arenadata/adcm:test or --staticimage some_repo/some_image:some_tag`

#### `--dontstop`

> If passed then ADCM containers will remain running after tests

Property | Value
---: | ---
value | `none`
default | `false`

#### `--adcm-image`

> Exact name of ADCM docker image to run tests on
>
> Incompatible with [`--adcm-images`](#--adcm-images) and [`--adcm-min-version`](#--adcm-min-version)

Property | Value
---: | ---
value | `valid image name:tag`
default | `arenadata/adcm:latest`

#### `--adcm-images`

> Names of ADCM docker images to run tests on.
> Each image name should be passed as individual arg
>
> Incompatible with [`--adcm-image`](#--adcm-image) and [`--adcm-min-version`](#--adcm-min-version)

Property | Value
---: | ---
value | `valid image name:tag`
default | `none`
example | `--adcm-images arenadata/adcm:2020.01.30.15 arenadata/adcm:2020.10.15.28`

#### `--adcm-min-version`

> If passed then tests will be executed on all ADCM release images
> newer than version passed
>
> Incompatible with [`--adcm-images`](#--adcm-images) and [`--adcm-image`](#--adcm-image)

Property | Value
---: | ---
value | `string of ADCM version format`
default | `none`
example | `--adcm-min-version 2020.01.30.15`

#### `--nopull`

> If passed then no pull action will be performed on `docker run`

Property | Value
---: | ---
value | `none`
default | `false`

### Mics

#### `--remote-executor-host`

> If passed then ADCM API will be initialized with external IP
> to allow incoming connections from any remote executor (ex. Selenoid)
> Tests will fail if remote host is unreachable.
> This option will be ignored if [`--remote-docker`](#--remote-docker) option is passed

Property | Value
---: | ---
value | `string with fqdn`
default | `none`

#### `--remote-docker`

> If passed then ADCM instances will be created on a remote host.
> Docker daemon should be running and be available with provided host:port


Property | Value
---: | ---
value | `string of host:port format`
default | `none`
example | `--remote-docker '10.92.7.14:2375'`

#### `--verbose-actions`

> If passed then ADCM actions will be started with 'verbose' checkbox selected.
> Applied only to action calls over adcm_client. 
> Does not affect UI action calls in tests.


Property | Value
---: | ---
value | `none`
default | `false`


## Writing tests for plugin

At the moment, the project has a set of tests, which is located in the `./tests` directory. Current tests and tests that
will be written should be based on usage of the `tesdir` fixture from the `pytester` plugin. This approach allow tests
to be run inside tests. Nested launch is important for us, since many functions and fixtures of the plugin depends on
launch parameters (`pytest` command-line options)

Source code of nested tests can be stored as:

1. `.py` files in `./tests/_test_files` directory
2. multiline string inside code of the test that will run nested test

### Example 1.

Given that the code for a nested test is stored in the `test_some.py` file. To run such a test, you need to run the
following code:

```python
def test_some_fixture(testdir):
    testdir.copy_example("test_some.py")
    result = testdir.runpytest()
    # This number determines the number of successful tests in the nested test
    result.assert_outcomes(passed=1)
```

### Example 2.

Given that the code for a nested test is stored in multiline string. To run such a test, you need to run the following
code:

```python
def test_some_fixture(testdir):
    testdir.makepyfile(
        """
        def test_some():
          assert True
        """
    )
    result = testdir.runpytest()
    # This number determines the number of successful tests in the nested test
    result.assert_outcomes(passed=1)
```

You can read more about writing tests for pytest plugins here
- [Testing plugins](https://docs.pytest.org/en/stable/writing_plugins.html?highlight=plugin#testing-plugins)

## How to run unit tests for plugin

To run plugin tests, you can execute this from your project root:

```
pip install -e .
pip install -r tests/requirements.txt
cd tests
pytest ./plugin --alluredir allure-result
```

To open allure report, you can execute this:

```
allure serve allure-result
```

## Pre-commit hook

We are using black, pylint and pre-commit to care about code formating and linting.

So you have to install pre-commit hook before you do something with code.

``` sh
pip install pre-commit # Or do it with your preffered way to install pip packages
pre-commit install
```

After this you will see invocation of black and pylint on every commit.
