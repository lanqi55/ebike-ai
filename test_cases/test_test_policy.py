"""在隔离且禁止联网的子进程中验证项目实际使用的 pytest 配置。"""

import json
import os
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest


pytestmark = pytest.mark.integration
TEST_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TEST_DIR.parent


@pytest.fixture
def policy_project(pytester, monkeypatch):
    # 子进程重新读取配置，不继承真实凭据或启用真实服务的运行参数。
    monkeypatch.setenv("DASHSCOPE_API_KEY", "policy-test-placeholder")
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
    for name in list(os.environ):
        if name.startswith("EBIKE_DB_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("PYTHONPATH", str(PROJECT_ROOT / "src"))
    monkeypatch.setenv("PYTHONIOENCODING", "utf-8")
    pytester.makefile(
        ".toml",
        pyproject=(PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"),
    )
    # 直接加载项目实际使用的测试钩子和 fixture，避免复制实现导致验证失真。
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
    """CI 必须排除真实服务用例，并在退出码和报告中如实反映失败。"""
    (policy_project.path / "test_cases" / "test_db_excluded.py").write_text(
        "import pytest\n@pytest.mark.integration\n@pytest.mark.db\ndef test_db_excluded():\n"
        "    pytest.fail('CI must exclude MySQL even with --run-db')\n",
        encoding="utf-8",
    )
    if failing:
        (policy_project.path / "test_cases" / "test_failure.py").write_text(
            "import pytest\n@pytest.mark.unit\ndef test_failure():\n"
            "    assert False, 'intentional CI failure probe'\n",
            encoding="utf-8",
        )

    result = policy_project.runpytest_subprocess(
        "-m", "not live and not db", "-q", "-rs",
        "--junitxml=reports/ci/junit.xml",
        "--alluredir=reports/ci/allure-results",
    # 即使意外传入真实模型开关，也不能覆盖 CI 对用例的筛选。
        "--run-live",
        "--run-db",
        timeout=60,
    )

    assert result.ret == (pytest.ExitCode.TESTS_FAILED if failing else pytest.ExitCode.OK)
    result.assert_outcomes(passed=1, failed=int(failing), deselected=3)
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


@pytest.mark.parametrize("args, marked", [
    ((), True), (("-m", "db"), True), (("--run-live",), True), ((), False),
])
def test_database_requires_its_own_flag(policy_project, monkeypatch, args, marked):
    # 仅配置凭据不能视为允许建立真实数据库连接。
    monkeypatch.setenv("EBIKE_DB_USER", "fake-user")
    monkeypatch.setenv("EBIKE_DB_PASSWORD", "fake-password")
    monkeypatch.setenv("EBIKE_DB_NAME", "ebike_ai_day11")
    (policy_project.path / "test_cases" / "test_db_gate.py").write_text(
        "import pytest\n"
        + ("@pytest.mark.db\n" if marked else "")
        + "def test_db_gate(db_connection_factory):\n"
        "    pytest.fail('Disabled MySQL test body must not run')\n",
        encoding="utf-8",
    )
    result = policy_project.runpytest_subprocess(
        "test_cases/test_db_gate.py", *args, "-q", "-rs", timeout=60,
    )
    result.assert_outcomes(skipped=1)
    result.stdout.fnmatch_lines(["*requires --run-db*" if not marked else "*require --run-db*"])


@pytest.mark.parametrize("database", [None, "not_the_practice_database"])
def test_database_flag_rejects_missing_config_or_wrong_database(policy_project, monkeypatch, database):
    if database:
        monkeypatch.setenv("EBIKE_DB_USER", "fake-user")
        monkeypatch.setenv("EBIKE_DB_PASSWORD", "fake-password")
        monkeypatch.setenv("EBIKE_DB_NAME", database)
    (policy_project.path / "test_cases" / "test_db_gate.py").write_text(
        "import pytest\n@pytest.mark.db\ndef test_db_gate(db_connection_factory):\n"
        "    pytest.fail('Invalid configuration must fail before test body')\n",
        encoding="utf-8",
    )
    result = policy_project.runpytest_subprocess(
        "test_cases/test_db_gate.py", "--run-db", "-q", timeout=60,
    )
    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines([
        "*only allow EBIKE_DB_NAME=ebike_ai_day11*" if database else "*Missing database configuration*"
    ])
    assert "fake-password" not in result.stdout.str()


@pytest.mark.parametrize("failing", [False, True], ids=["success", "failure"])
def test_database_fixture_cleans_all_connections(policy_project, monkeypatch, failing):
    monkeypatch.setenv("EBIKE_DB_USER", "fake-user")
    monkeypatch.setenv("EBIKE_DB_PASSWORD", "fake-password")
    monkeypatch.setenv("EBIKE_DB_NAME", "ebike_ai_day11")
    (policy_project.path / "test_cases" / "test_db_cleanup.py").write_text(
        '''from pathlib import Path
import pytest
import ebike_ai.database as database

def record(event):
    with (Path(__file__).parent.parent / "db-events.txt").open("a") as stream:
        stream.write(event + "\\n")

class FakeConnection:
    def rollback(self):
        record("rollback")
    def close(self):
        record("close")

@pytest.fixture(autouse=True)
def fake_driver(monkeypatch):
    monkeypatch.setattr(database, "connect_database", lambda settings: FakeConnection())

@pytest.mark.db
def test_cleanup(db_connection_factory):
    db_connection_factory()
    db_connection_factory()
'''
        + ("    pytest.fail('intentional body failure')\n" if failing else ""),
        encoding="utf-8",
    )
    result = policy_project.runpytest_subprocess(
        "test_cases/test_db_cleanup.py", "--run-db", "-q", timeout=60,
    )
    result.assert_outcomes(passed=int(not failing), failed=int(failing))
    assert (policy_project.path / "db-events.txt").read_text().splitlines() == [
        "rollback", "close", "rollback", "close",
    ]
