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
"""Some utils of plugin"""


import os
import random
import re
import string
from contextlib import AbstractContextManager
from inspect import getfullargspec
from time import sleep, time
from typing import Callable, Iterable, List, Tuple, Type, Union, Optional

import allure
import pytest
from _pytest.fixtures import FixtureFunctionMarker, _FixtureFunction
from _pytest.mark import MarkDecorator
from adcm_client.base import ObjectNotFound
from adcm_client.objects import Cluster, Host, Task
from allure_commons.reporter import AllureReporter
from allure_pytest.listener import AllureListener
from decorator import decorator


def remove_host(host: Host) -> Task:
    """
    Run action remove for host
    """
    return host.action(name="remove").run()


def get_or_add_service(cluster: Cluster, service_name: str):
    """
    Add service if it wasn't added before and return it
    """
    try:
        return cluster.service(name=service_name)
    except ObjectNotFound:
        return cluster.service_add(name=service_name)


def random_string(strlen: int = 10) -> str:
    """
    Generate random string

    >>> type(random_string())
    <class 'str'>
    >>> all([True if char in string.ascii_letters else False for char in random_string()])
    True
    >>> len(random_string())
    10
    >>> len(random_string(strlen=0))
    0
    >>> len(random_string(strlen=1))
    1
    """
    return "".join([random.choice(string.ascii_letters) for _ in range(strlen)])


def random_special_chars(strlen: int = 3) -> str:
    """
    Generate special chars

    >>> type(random_special_chars())
    <class 'str'>
    >>> all([True if char in string.punctuation else False for char in random_special_chars()])
    True
    >>> len(random_special_chars())
    3
    >>> len(random_special_chars(strlen=0))
    0
    >>> len(random_special_chars(strlen=1))
    1
    """
    return "".join([random.choice(string.punctuation) for _ in range(strlen)])


def random_string_list(num: int = 10) -> List[str]:
    """
    Generate list of random strings

    >>> type(random_string_list())
    <class 'list'>
    >>> all([True if type(obj) is str else False for obj in random_string_list()])
    True
    >>> len(random_string_list())
    10
    >>> len(random_string_list(num=0))
    0
    >>> len(random_string_list(num=1))
    1
    """
    return [random_string() for _ in range(num)]


def ordered_dict_to_dict(value: dict) -> dict:
    """
    Convert OrderedDict to dict

    :param value: some OrderedDict object

    >>> ordered_dict_to_dict({})
    {}
    >>> ordered_dict_to_dict({'key': 'value'})
    {'key': 'value'}
    >>> ordered_dict_to_dict({'key': {'nested_key': 'nested_value'}})
    {'key': {'nested_key': 'nested_value'}}
    >>> from collections import OrderedDict
    >>> d = {'banana': 3, 'apple': 4, 'pear': 1, 'orange': 2}
    >>> ordered_dict_to_dict(OrderedDict(d.items()))
    {'banana': 3, 'apple': 4, 'pear': 1, 'orange': 2}
    >>> d = {'banana': 3, 'apple': 4, 'pear': 1, 'orange': {'some_key': 'some_value'}}
    >>> ordered_dict_to_dict(OrderedDict(d.items()))
    {'banana': 3, 'apple': 4, 'pear': 1, 'orange': {'some_key': 'some_value'}}
    >>> d = {'banana': 3, 'apple': 4, 'pear': 1, 'orange': 2}
    >>> ordered_dict_to_dict(OrderedDict(sorted(d.items(), key=lambda t: t[0])))
    {'apple': 4, 'banana': 3, 'orange': 2, 'pear': 1}
    """
    for k, v in value.items():
        if isinstance(v, dict):
            value[k] = ordered_dict_to_dict(v)
    return dict(value)


def deep_merge(first: dict, second: dict) -> dict:
    """
    Dict deep merge function
    Merge recursive second dict in first and return it

    >>> deep_merge({},{})
    {}
    >>> deep_merge({'key': 'value'}, {'key': 'value'})
    {'key': 'value'}
    >>> deep_merge({'key': 'value'}, {'key': 'new_value', 'second_key': 'second_value'})
    {'key': 'new_value', 'second_key': 'second_value'}
    >>> deep_merge(
    ...     {'key': 'value', 'dict_key': {'nested_key': 'nested_value'}},
    ...     {
    ...         'key': 'value',
    ...         'dict_key': {'nested_key': 'new_nested_value', 'nested_dict_key': {}},
    ...         'flat_key': 'flat_value'
    ...     }
    ... )
    {'key': 'value', 'dict_key': {'nested_key': 'new_nested_value', 'nested_dict_key': {}}, 'flat_key': 'flat_value'}
    """
    for key in second:
        if key in first:
            if isinstance(first[key], dict) and isinstance(second[key], dict):
                deep_merge(first[key], second[key])
            else:
                first[key] = second[key]
        else:
            first[key] = second[key]
    return first


def check_mutually_exclusive(options, *opts) -> bool:
    """
    Checks if there are mutually exclusive options

    >>> obj = lambda: None
    >>> obj.attrib1 = 1
    >>> obj.attrib2 = 2
    >>> check_mutually_exclusive(obj, *["attrib1"])
    False
    >>> obj = lambda: None
    >>> obj.attrib1 = 1
    >>> obj.attrib2 = 2
    >>> obj.attrib3 = 3
    >>> check_mutually_exclusive(obj, *["attrib1", "attrib2"])
    True
    """
    count = 0
    for opt in opts:
        if getattr(options, opt):
            count += 1
    return count > 1


def get_subdirs_iter(filename: str, *subdirs) -> Iterable[str]:
    """
    Get iterable subdirs

    >>> type(get_subdirs_iter(__file__))
    <class 'generator'>
    >>> type(get_subdirs_iter(__file__, "subdir1", "subdir2"))
    <class 'generator'>
    """

    datadir = get_data_dir(filename)
    dirname = os.path.join(datadir, *subdirs)
    for subpath in os.listdir(dirname):
        full = os.path.join(dirname, subpath)
        if os.path.isdir(full):
            yield full


def get_data_dir(filename: str, *subdirs) -> str:
    """That function returns a name of data dir for test.

    It's nice for every test to store test data in <module_name>_data dir.
    That function returns path to that dir.
    Optionally it joins data dir with list of subdirs. That allow to do
    one call to build a path

    Example:

    get_data_dir(__file__, "bundles", "cluster")

    Return will be:
    "<filename>/bundles/cluster"

    NOTE: That function doesn't check existing of a path.

    >>> get_data_dir(__file__).endswith("_data")
    True
    >>> get_data_dir(__file__, "subdir1", "subdir2").endswith("_data/subdir1/subdir2")
    True
    >>> __file__ == f"{get_data_dir(__file__).split('_data')[0]}.py"
    True
    """
    filename = filename[:-3]  # Strip .py from name
    filename = filename + "_data"
    filename = os.path.join(filename, *subdirs)
    return filename


def get_data_subdirs_as_parameters(filename: str, *subdirs) -> Tuple[List[str], List[str]]:
    """That function returns subdirs of <filename>_data in parametrize form

    It's really useful to iterate over subdirs with pytest.mark.parametrize.
    It returns two list:
    - list with pathes
    - list with names

    You could use it in code like that
    cases, ids = get_data_subdirs_as_parameters(__file__)
    @pytest.mark.parametrize("subdir", cases, ids=ids)

    Besides, it is possible to go deeply with the os.path.join, which is called
    against any argument from second
    cases, ids = get_data_subdirs_as_parameters(__file__, "subdirname", "subsubdirname")
    @pytest.mark.parametrize("subdir", cases, ids=ids)

    >>> @contextlib.contextmanager
    ... def _mk_dir(tmp_dir):
    ...     os.mkdir(tmp_dir)
    ...     yield tmp_dir
    ...     shutil.rmtree(tmp_dir)
    >>> test_dir = f"{__file__.strip('.py')}_data"
    >>> with _mk_dir(test_dir):
    ...     get_data_subdirs_as_parameters(__file__)
    ([], [])
    >>> dirs = [f"{test_dir}/level1", f"{test_dir}/level1/level2_0", f"{test_dir}/level1/level2_1"]
    >>> with _mk_dir(test_dir), _mk_dir(dirs[0]), _mk_dir(dirs[1]), _mk_dir(dirs[2]):
    ...         get_data_subdirs_as_parameters(__file__, "level1") == ( dirs[1:], ['level2_0', "level2_1"])
    True
    """
    datadir = get_data_dir(filename)
    dirname = os.path.join(datadir, *subdirs)
    paths = []
    ids = []
    for subpath in sorted(os.listdir(dirname)):
        paths.append(f"{dirname}/{subpath}")
        ids.append(subpath)
    return paths, ids


def parametrize_by_data_subdirs(filename: str, *path) -> MarkDecorator:
    """This is a decorator useful to combine functionality of
    get_data_subdirs_as_parameters and pytest.mark.parametrize.

    Example:

    @parametrize_by_data_subdirs(__file__)
    def test_over_dirs(path):
        pass

    In that case function find directory <filename>_data and parametrize(iterate)
    test case over subdirs.

    Sometimes you need to go deeper than in _data folder:

    @parametrize_by_data_subdirs(__file__, 'subdir_leve1', 'subdir_level2'):
    def test_over_dirs(path):
        pass

    In that case test will iterate over <filename>_data/subdir_leve1/subdir_level2/* dirs.

    >>> @contextlib.contextmanager
    ... def _mk_dir(tmp_dir):
    ...     os.mkdir(tmp_dir)
    ...     yield tmp_dir
    ...     shutil.rmtree(tmp_dir)
    >>> test_dir = f"{__file__.strip('.py')}_data"
    >>> dirs = [f"{test_dir}/level1", f"{test_dir}/level1/level2_0", f"{test_dir}/level1/level2_1"]
    >>> with _mk_dir(test_dir), _mk_dir(dirs[0]), _mk_dir(dirs[1]), _mk_dir(dirs[2]):
    ...         mark_decorator = parametrize_by_data_subdirs(__file__, "level1")
    >>> mark_decorator.kwargs
    {'ids': ['level2_0', 'level2_1']}
    >>> mark_decorator.args == ('path', dirs[1:])
    True
    """
    cases, ids = get_data_subdirs_as_parameters(filename, *path)
    return pytest.mark.parametrize("path", cases, ids=ids)


def fixture_parametrized_by_data_subdirs(
    filename: str, *path, scope="function"
) -> Union[FixtureFunctionMarker, _FixtureFunction]:
    """That is a combination of parametrized fixture and get_data_subdirs_as parameters

    That is useful when you want to parametrize fixture over subdirs.

    Example:

    @fixture_parametrized_by_data_subdirs(__file__, 'cluster_and_service', scope='module')
    def cluster(sdk_client_ms: ADCMClient, request):
        assert request.param is not None

    Note:

    Due to strange pytest logic you can't parametrize a fixture with right way
    (over regular pytest.mark.parametrize decorator). That is why we have strange
    access to information over request.param.

    >>> @contextlib.contextmanager
    ... def _mk_dir(tmp_dir):
    ...     os.mkdir(tmp_dir)
    ...     yield tmp_dir
    ...     shutil.rmtree(tmp_dir)
    >>> test_dir = f"{__file__.strip('.py')}_data"
    >>> with _mk_dir(test_dir):
    ...     fixture_function_marker = fixture_parametrized_by_data_subdirs(__file__)
    >>> fixture_function_marker.scope
    'function'
    >>> fixture_function_marker.ids
    ()
    >>> fixture_function_marker.params
    ()
    >>> dirs = [f"{test_dir}/level1", f"{test_dir}/level1/level2_0", f"{test_dir}/level1/level2_1"]
    >>> with _mk_dir(test_dir), _mk_dir(dirs[0]), _mk_dir(dirs[1]), _mk_dir(dirs[2]):
    ...         fixture_function_marker = fixture_parametrized_by_data_subdirs(
    ...             __file__, "level1", scope='module'
    ...         )
    >>> fixture_function_marker.scope
    'module'
    >>> fixture_function_marker.ids
    ('level2_0', 'level2_1')
    >>> fixture_function_marker.params == tuple(dirs[1:])
    True
    """
    cases, ids = get_data_subdirs_as_parameters(filename, *path)
    return pytest.fixture(scope=scope, params=cases, ids=ids)


def wait_until_step_succeeds(func, timeout: Union[int, float] = 300, period: Union[int, float] = 10, **kwargs):
    """
    Repeat `func` with `kwargs` until successful
    >>> states = iter([False, False, True])
    >>> def step():
    ...     assert next(states), "Still failed"

    >>> wait_until_step_succeeds(step, timeout=0.5, period=0.1)
    >>> states = iter([False, False, True])
    >>> wait_until_step_succeeds(step, timeout=0.2, period=0.1)
    Traceback (most recent call last):
    ...
    AssertionError: Step "step" failed after retrying 0.2 seconds. The last error was: Still failed
    """
    with allure.step(f'Wait until "{func.__name__}" succeeds'):
        start = time()
        last_error = None
        while time() - start < timeout:
            try:
                func(**kwargs)
            except AssertionError as err:
                last_error = err
                sleep(period)
                continue
            break
        else:
            raise AssertionError(
                f'Step "{func.__name__}" failed after retrying {timeout} seconds. ' f"The last error was: {last_error}"
            )


class catch_failed(AbstractContextManager):  # pylint: disable=invalid-name
    """
    ContextManager to catch some errors and raise AssertionError with the given message.
    >>> class SomeException(Exception):
    ...     pass
    >>> with catch_failed(SomeException, "Oops!"):
    ...     raise SomeException("Inner exception")
    Traceback (most recent call last):
        ...
    AssertionError: Oops!
    """

    __tracebackhide__ = True

    def __init__(self, exctype: Type[Exception], msg: str):
        self._msg = msg
        self._exctype = exctype

    def __enter__(self):
        pass

    def __exit__(self, exctype, excinst, exctb):
        if exctype is not None and issubclass(exctype, self._exctype):
            raise AssertionError(self._msg) from excinst


def expectparam(type_: Type) -> Callable:
    """Check that request.param exists and has a given type.
    NB! Use before pytest.fixture() decorator.

    >>> @expectparam(int)
    ... def test(request):
    ...    print("pass")
    >>> request = lambda _: ...
    >>> test(request)  # doctest: +IGNORE_EXCEPTION_DETAIL
    Traceback (most recent call last):
    ...
    ValueError: Expecting <class 'str'> instance as a fixture param
    >>> request.param = 42
    >>> test(request)
    pass
    >>> request.param = "42"
    >>> test(request)  # doctest: +IGNORE_EXCEPTION_DETAIL
    Traceback (most recent call last):
    ...
    ValueError: Expecting <class 'str'> instance as a fixture param
    """

    @decorator
    def impl(func: Callable, *args, **kwargs):
        __tracebackhide__ = True  # pylint: disable=unused-variable

        if getattr(func, "_pytestfixturefunction", False):
            raise ValueError("expectparam decorator should be applied before @pytest.fixture()")

        funspec = getfullargspec(func)
        request = args[funspec.args.index("request")]
        if not isinstance(getattr(request, "param", None), type_):
            raise ValueError(f"Expecting {type_} instance as a fixture param")

        return func(*args, **kwargs)

    return impl


def allure_reporter(config) -> Optional[AllureReporter]:
    """Get Allure Reporter from pytest plugins"""
    listener: AllureListener = next(
        filter(
            lambda plugin: (isinstance(plugin, AllureListener)),
            dict(config.pluginmanager.list_name_plugin()).values(),
        ),
        None,
    )
    return listener.allure_logger if listener else None


def func_name_to_title(func_name):
    """Translate test func name to human-readable title
    >>> func_name_to_title("test_should_not_create_service_with_invalid_config")
    'Should not create service with invalid config'
    >>> func_name_to_title("test_parametrized[first_param-second_param]")
    'Parametrized[first_param-second_param]'
    >>> func_name_to_title("This is custom title")
    'This is custom title'
    """
    found = re.findall(r"^test_(\w+)(\[.*])?", func_name)
    if not found:
        return func_name
    func_name, params = found[0]
    func_name = func_name.replace("_", " ").capitalize()
    return func_name + params
