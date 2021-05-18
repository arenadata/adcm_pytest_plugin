"""Common methods for plugin tests"""

import allure

def run_tests(
    testdir,
    filename: str = None,
    py_file: str = None,
    additional_opts: list = None,
    outcomes=None,
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
    elif py_file:
        testdir.makepyfile(py_file)

    opts = ["-s", "-v", *additional_opts]
    with allure.step(f"Run test {filename}"):
        result = testdir.runpytest(*opts)
        allure.attach('\n'.join(result.outlines), name='Internal test output',
                      attachment_type=allure.attachment_type.TEXT)
        if outcomes:
            result.assert_outcomes(**outcomes)
        else:
            result.assert_outcomes(passed=1)
        return result
