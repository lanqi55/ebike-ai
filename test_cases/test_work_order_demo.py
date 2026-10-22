"""交互演示必须显式开启，并在中断时尝试清理数据。"""

from unittest.mock import MagicMock

import pytest

from scripts import work_order_demo as demo


pytestmark = pytest.mark.unit


def test_demo_without_switch_never_reads_configuration(monkeypatch):
    config = MagicMock(side_effect=AssertionError("must not read config"))
    monkeypatch.setattr(demo.DatabaseConfig, "from_env", config)
    with pytest.raises(SystemExit) as caught:
        demo.main([])
    assert caught.value.code == 2
    config.assert_not_called()


@pytest.mark.parametrize("failure", [KeyboardInterrupt(), EOFError(), RuntimeError("fake-password")])
def test_demo_interruption_or_failure_cleans_up_without_exposing_error(monkeypatch, capsys, failure):
    lab = MagicMock()
    lab.order.return_value = {"work_order_no": "demo"}
    monkeypatch.setattr(demo, "WorkOrderLab", MagicMock(return_value=lab))
    monkeypatch.setattr(demo.DatabaseConfig, "from_env", MagicMock())
    monkeypatch.setattr("builtins.input", MagicMock(side_effect=failure))
    assert demo.main(["--run-db"]) == 1
    lab.cleanup.assert_called_once_with()
    assert "fake-password" not in capsys.readouterr().out


def test_demo_cleanup_failure_returns_nonzero(monkeypatch, capsys):
    lab = MagicMock()
    lab.order.return_value = {"work_order_no": "demo"}
    lab.records = {"work_order": []}
    lab.cleanup.side_effect = RuntimeError("fake-password")
    monkeypatch.setattr(demo, "WorkOrderLab", MagicMock(return_value=lab))
    monkeypatch.setattr(demo.DatabaseConfig, "from_env", MagicMock())
    monkeypatch.setattr("builtins.input", MagicMock(return_value=""))
    assert demo.main(["--run-db"]) == 1
    output = capsys.readouterr().out
    assert "fake-password" not in output
    assert "清理失败" in output
