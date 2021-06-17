"""Common methods for plugin tests"""

from typing import Optional

import allure


def run_tests(
    testdir,
    testfile_path: str = "",
    makepyfile_str: str = "",
    additional_opts: Optional[list] = None,
    outcomes=None,
):
    """
    Run tests with pytest parameters from .py file or multiline string
    :param testdir:
    :param testfile_path: name of file from the directory "_test_files" which will be running
    :param makepyfile_str: multiline string for makepyfile method which will be running if param 'testfile_path' is None
    :param additional_opts: list of additional pytest launch parameters
    :param outcomes: optional outcomes expect. Ex. {"failed":1}
    """
    assert testfile_path or makepyfile_str, "At least one of the `testfile_path` or `makepyfile_str` should be passed."

    if testfile_path:
        testdir.copy_example(testfile_path)
    elif makepyfile_str:
        testdir.makepyfile(makepyfile_str)

    additional_opts = additional_opts or []
    opts = ["-s", "-v", *additional_opts]
    step_title = f"Run file {testfile_path}" if testfile_path else "Run test from multiline string"
    with allure.step(step_title):
        result = testdir.runpytest(*opts)
        allure.attach(
            "\n".join(result.outlines),
            name="Internal test output",
            attachment_type=allure.attachment_type.TEXT,
        )
        args = outcomes or dict(passed=1)
        result.assert_outcomes(**args)
        return result
