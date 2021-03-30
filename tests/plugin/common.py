"""Common methods for plugin tests"""

import os


def run_tests(
    testdir,
    filename: str = None,
    py_file: str = None,
    additional_opts: list = None,
    additioanal_files: list = None,
    outcomes=None
):
    """
    Run tests with pytest parameters from .py file or multiline string
    :param testdir:
    :param filename: name of file from the directory "_test_files" which will be running
    :param py_file: multiline string for makepyfile method which will be running if param 'filename' is None
    :param additional_opts: list of additional pytest launch parameters
    :param outcomes: optional outcomes expect. Ex. {"failed":1}
    """
    if additional_opts is None:
        additional_opts = []
    if filename:
        testdir.copy_example(filename)
        if additioanal_files:
            for file in additioanal_files:
                testdir.copy_example(file)
    elif py_file:
        testdir.makepyfile(py_file)

    opts = ["-s", "-v", *additional_opts]
    result = testdir.runpytest(*opts)
    if outcomes:
        result.assert_outcomes(**outcomes)
    else:
        result.assert_outcomes(passed=1)
    return result
