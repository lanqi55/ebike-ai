# conftest.py - pytest 全局配置 + 共享 fixture
# 作用1：确保 test_cases/ 子目录能 import 项目根目录的模块
# 作用2：控制真实模型测试的开关，并提供共享 fixture

import sys
import os
from contextlib import ExitStack
import pytest

# 1. 先把项目根目录加进 Python 搜索路径（必须在 import 项目模块之前）
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

# 2. 再 import 项目模块
from langchain_community.chat_models import ChatTongyi
from ebike_ai.config import config
from ebike_ai.core.tool_registry import ToolRegistry
from ebike_ai.core.react_loop import AgentLoop
from ebike_ai.tools.hardware_tools import create_hardware_tools
from ebike_ai.tools.knowledge_tools import create_knowledge_tools


pytest_plugins = ["pytester"]


@pytest.fixture
def work_order_lab(request):
    """显式开启会提交数据的测试；与第 12 天仅靠回滚清理的 fixture 分开。"""
    if not request.config.getoption("--run-db"):
        pytest.skip("Work order lab requires --run-db")
    from ebike_ai.database import DatabaseConfig, DatabaseConfigError
    from test_cases.mysql_work_orders import WorkOrderLab

    try:
        settings = DatabaseConfig.from_env()
    except DatabaseConfigError as exc:
        pytest.fail(str(exc), pytrace=False)
    if settings.database != "ebike_ai_day11":
        pytest.fail("Work order lab only allows ebike_ai_day11", pytrace=False)
    lab = WorkOrderLab(settings, os.path.join(PROJECT_ROOT, "reports", "week3", "manifests"))
    try:
        try:
            lab.prepare()
        except Exception:
            pytest.fail("Work order lab setup failed; check local database and schema (details suppressed)", pytrace=False)
        yield lab
    finally:
        try:
            lab.cleanup()
        except Exception:
            pytest.fail(f"Work order lab cleanup failed; inspect exact identifiers in {lab.manifest_path}", pytrace=False)


def pytest_addoption(parser):
    parser.addoption(
        "--run-db", action="store_true", default=False,
        help="Allow real MySQL tests in ebike_ai_day11 (requires EBIKE_DB_* configuration)",
    )
    parser.addoption(
        "--run-live",
        action="store_true",
        default=False,
        help="Allow live model/embedding tests (requires a Key; may incur charges)",
    )


def pytest_collection_modifyitems(config, items):
    skip_live = pytest.mark.skip(reason="Live tests require --run-live")
    skip_db = pytest.mark.skip(reason="MySQL tests require --run-db")
    for item in items:
        if not config.getoption("--run-live") and item.get_closest_marker("live") is not None:
            item.add_marker(skip_live)
        if not config.getoption("--run-db") and item.get_closest_marker("db") is not None:
            item.add_marker(skip_db)


@pytest.fixture
def db_connection_factory(request):
    """第二道开关检查也保护未标记的测试；每个连接都执行回滚清理。"""
    if not request.config.getoption("--run-db"):
        pytest.skip("MySQL fixture requires --run-db")
    from ebike_ai.database import DatabaseConfig, DatabaseConfigError, connect_database

    try:
        settings = DatabaseConfig.from_env()
    except DatabaseConfigError as exc:
        pytest.fail(str(exc), pytrace=False)
    if settings.database != "ebike_ai_day11":
        pytest.fail("Database tests only allow EBIKE_DB_NAME=ebike_ai_day11", pytrace=False)

    cleanup = ExitStack()

    def open_connection():
        from ebike_ai.database import DatabaseConnectionError

        try:
            connection = connect_database(settings)
        except DatabaseConnectionError as exc:
            pytest.fail(str(exc), pytrace=False)
        cleanup.callback(connection.close)
        cleanup.callback(connection.rollback)
        return connection

    with cleanup:
        yield open_connection


@pytest.fixture(scope="module")
def llm(request):
    """模块级 LLM：一个测试文件只初始化一次，所有测试复用同一个对象"""
    # 第二道检查：即使调用者忘记标 live，也不能仅凭 Key 触发真实请求。
    if not request.config.getoption("--run-live"):
        pytest.skip("Live LLM fixture requires --run-live")
    # 没配 API key 就跳过，而不是报一堆鉴权错误
    if not config.llm.api_key.strip():
        pytest.skip("DASHSCOPE_API_KEY is not set; skipping live LLM tests")
    return ChatTongyi(
        model=config.llm.model,
        dashscope_api_key=config.llm.api_key,
        temperature=config.llm.temperature,
        max_retries=1,
        model_kwargs={"max_tokens": config.llm.max_tokens, "request_timeout": config.llm.request_timeout},
    )


@pytest.fixture(scope="module")
def registry():
    """模块级工具注册中心：工具只注册一次"""
    reg = ToolRegistry()
    for tool in create_hardware_tools():
        reg.register(tool)
    for tool in create_knowledge_tools():
        reg.register(tool)
    return reg


@pytest.fixture()  # 默认 function 级别：每个测试一个全新 Agent，避免短期记忆串味
def agent(llm, registry):
    """函数级 Agent：由 llm + registry 组装，每个测试独立"""
    return AgentLoop(llm=llm, registry=registry, max_iter=10)
