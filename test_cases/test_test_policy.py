"""Exercise the real pytest configuration in isolated, network-free subprocesses."""

import json
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest


pytestmark = pytest.mark.integration
TEST_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TEST_DIR.parent


@pytest.fixture
def policy_project(pytester, monkeypatch):
    # The child reads config afresh; never inherit a real credential or run flag.
    monkeypatch.setenv("DASHSCOPE_API_KEY", "policy-test-placeholder")
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
    monkeypatch.setenv("PYTHONPATH", str(PROJECT_ROOT / "src"))
    monkeypatch.setenv("PYTHONIOENCODING", "utf-8")
    pytester.makefile(
        ".toml",
        pyproject=(PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"),
    )
    # Reuse production test hooks/fixtures, rather than copying their logic.
    pytester.makeconftest(
        (TEST_DIR / "conftest.py").read_text(encoding="utf-8")
        + '''
from pathlib import Path
from types import SimpleNamespace
import socket

def block_network(*args, **kwargs):
    pytest.fail("Network access is forbidden in policy tests", pytrace=False)

socket.create_connection = block_network
socket.socket.connect = block_network
socket.socket.connect_ex = block_network

def record_call(event):
    with (Path(__file__).parent / "model-calls.txt").open("a", encoding="utf-8") as log:
        log.write(event + "\\n")

class FakeChatTongyi:
    def __init__(self, **kwargs):
        record_call("created")

    def bind_tools(self, schemas):
        return self

    def invoke(self, messages):
        record_call("invoked")
        return SimpleNamespace(content="电芯 cell3 低于 电池 老化", tool_calls=None)

ChatTongyi = FakeChatTongyi
'''
    )
    child_tests = pytester.path / "test_cases"
    child_tests.mkdir()
    (child_tests / "test_agent_eval.py").write_text(
        (TEST_DIR / "test_agent_eval.py").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (child_tests / "test_offline.py").write_text(
        "import pytest\n@pytest.mark.unit\ndef test_offline():\n    assert 1 + 1 == 2\n",
        encoding="utf-8",
    )
    return pytester


def assert_model_not_created(project):
    assert not (project.path / "model-calls.txt").exists()


@pytest.mark.parametrize("has_key", [False, True], ids=["no-key", "fake-key"])
def test_default_run_is_offline(policy_project, monkeypatch, has_key):
    if not has_key:
        monkeypatch.delenv("DASHSCOPE_API_KEY")

    result = policy_project.runpytest_subprocess("-q", "-rs", timeout=60)

    result.assert_outcomes(passed=1, skipped=2)
    result.stdout.fnmatch_lines(["*Live tests require --run-live*"])
    assert_model_not_created(policy_project)


@pytest.mark.parametrize(
    "selection",
    [("-m", "live"), ("-m", "evaluation"), ("test_cases/test_agent_eval.py",)],
    ids=["live-marker", "evaluation-marker", "direct-path"],
)
def test_selection_does_not_enable_live_calls(policy_project, selection):
    result = policy_project.runpytest_subprocess(*selection, "-q", "-rs", timeout=60)

    result.assert_outcomes(skipped=2, deselected=0 if len(selection) == 1 else 1)
    result.stdout.fnmatch_lines(["*Live tests require --run-live*"])
    assert_model_not_created(policy_project)


def test_llm_fixture_requires_flag_even_without_live_marker(policy_project):
    (policy_project.path / "test_cases" / "test_missing_marker.py").write_text(
        "import pytest\n@pytest.mark.unit\ndef test_missing_marker(llm):\n"
        "    pytest.fail('The unmarked test must not execute')\n",
        encoding="utf-8",
    )

    result = policy_project.runpytest_subprocess(
        "test_cases/test_missing_marker.py", "-q", "-rs", timeout=60
    )

    result.assert_outcomes(skipped=1)
    result.stdout.fnmatch_lines(["*Live LLM fixture requires --run-live*"])
    assert_model_not_created(policy_project)


def test_live_flag_without_key_skips_clearly(policy_project, monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY")

    result = policy_project.runpytest_subprocess(
        "-m", "live", "--run-live", "-q", "-rs", timeout=60
    )

    result.assert_outcomes(skipped=2, deselected=1)
    result.stdout.fnmatch_lines(["*DASHSCOPE_API_KEY is not set*"])
    assert_model_not_created(policy_project)


@pytest.mark.parametrize("selection", [(), ("-m", "live")], ids=["all", "live-only"])
def test_flag_and_key_allow_fake_model_execution(policy_project, selection):
    result = policy_project.runpytest_subprocess(
        *selection, "--run-live", "-q", timeout=60
    )

    result.assert_outcomes(passed=2 if selection else 3, deselected=1 if selection else 0)
    assert (policy_project.path / "model-calls.txt").read_text(encoding="utf-8").splitlines() == [
        "created", "invoked", "invoked"
    ]


@pytest.mark.parametrize("flags", [(), ("--run-live",)], ids=["default", "live-enabled"])
def test_collection_does_not_create_model(policy_project, flags):
    result = policy_project.runpytest_subprocess(
        "--collect-only", "-q", "-m", "evaluation", *flags, timeout=60
    )

    assert result.ret == pytest.ExitCode.OK
    result.stdout.fnmatch_lines(["*2/3 tests collected*"])
    assert_model_not_created(policy_project)


def test_unknown_marker_is_a_collection_error(policy_project):
    (policy_project.path / "test_cases" / "test_bad_marker.py").write_text(
        "import pytest\n@pytest.mark.lvie\ndef test_typo():\n    pass\n",
        encoding="utf-8",
    )

    result = policy_project.runpytest_subprocess("-q", timeout=60)

    assert result.ret == pytest.ExitCode.INTERRUPTED
    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(["*'lvie' not found in*markers*configuration option*"])
    assert_model_not_created(policy_project)


@pytest.mark.parametrize("failing", [False, True], ids=["success", "failure"])
def test_ci_selection_exit_status_and_reports(policy_project, failing):
    """CI must exclude live cases and preserve failures in its exit code/reports."""
    if failing:
        (policy_project.path / "test_cases" / "test_failure.py").write_text(
            "import pytest\n@pytest.mark.unit\ndef test_failure():\n"
            "    assert False, 'intentional CI failure probe'\n",
            encoding="utf-8",
        )

    result = policy_project.runpytest_subprocess(
        "-m", "not live", "-q", "-rs",
        "--junitxml=reports/ci/junit.xml",
        "--alluredir=reports/ci/allure-results",
        # Even an accidentally supplied live flag must not override CI selection.
        "--run-live",
        timeout=60,
    )

    assert result.ret == (pytest.ExitCode.TESTS_FAILED if failing else pytest.ExitCode.OK)
    result.assert_outcomes(passed=1, failed=int(failing), deselected=2)
    assert_model_not_created(policy_project)

    report_dir = policy_project.path / "reports" / "ci"
    suite = ET.parse(report_dir / "junit.xml").getroot().find("testsuite")
    assert suite is not None
    assert int(suite.attrib["tests"]) == 1 + int(failing)
    assert int(suite.attrib["failures"]) == int(failing)
    assert int(suite.attrib["errors"]) == 0
    assert int(suite.attrib["skipped"]) == 0

    allure_results = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in (report_dir / "allure-results").glob("*-result.json")
    ]
    assert {entry["name"]: entry["status"] for entry in allure_results} == {
        "test_offline": "passed",
        **({"test_failure": "failed"} if failing else {}),
    }
