"""使用独立的新事务，为已有车辆创建工单。"""

from collections.abc import Callable
from datetime import datetime

import pymysql

from ebike_ai.database import (
    DatabaseConfig, DatabaseConfigError, DatabaseConnectionError, connect_database,
)
from ebike_ai.repositories.battery import BatteryRepository
from ebike_ai.repositories.vehicle import VehicleRepository
from ebike_ai.repositories.work_order import WorkOrderRepository


class WorkOrderError(RuntimeError):
    """对外错误使用固定提示，不包含驱动原始错误或输入内容。"""

    def __init__(self, message: str):
        super().__init__(message)
        self.rollback_failed = False
        self.close_failed = False


class VehicleNotFoundError(WorkOrderError):
    pass


class BatteryNotFoundError(WorkOrderError):
    pass


class BatteryVehicleMismatchError(WorkOrderError):
    pass


class WorkOrderPersistenceError(WorkOrderError):
    pass


class DuplicateWorkOrderError(WorkOrderPersistenceError):
    """插入时触发了工单业务编号的唯一约束。"""


class WorkOrderNotFoundError(WorkOrderError):
    pass


class WorkOrderCommitUnknownError(WorkOrderPersistenceError):
    """提交响应异常，无法据此判断 MySQL 是否已完成提交。"""


class WorkOrderCleanupError(WorkOrderError):
    """提交成功但关闭连接失败；调用方不得重复创建工单。"""

    def __init__(self, work_order_id: int):
        super().__init__("Work order committed, but connection close failed; do not retry creation")
        self.work_order_id = work_order_id
        self.close_failed = True


def _open_connection():
    return connect_database(DatabaseConfig.from_env())


class WorkOrderService:
    def __init__(self, connection_factory: Callable = _open_connection):
        # 连接工厂每次必须返回独立的新连接，并设置 autocommit=False。
        self.connection_factory = connection_factory

    def create_work_order(
        self, work_order_no: str, vehicle_id: int, reported_symptom: str,
        report_source: str, *, battery_id: int | None = None,
        report_source_note: str | None = None, received_at: datetime | None = None,
        notes: str | None = None,
    ) -> int:
        """校验归属后插入并提交；任何失败都不自动重试。"""
        try:
            connection = self.connection_factory()
        except (DatabaseConfigError, DatabaseConnectionError):
            raise
        except Exception:
            raise WorkOrderPersistenceError("Could not open work order connection") from None

        error = None
        committing = False
        committed = False
        rollback_failed = False
        close_failed = False
        try:
            vehicle = VehicleRepository(connection).get_by_id(vehicle_id)
            if vehicle is None:
                raise VehicleNotFoundError("Vehicle does not exist")
            if battery_id is not None:
                battery = BatteryRepository(connection).get_by_id_for_update(battery_id)
                if battery is None:
                    raise BatteryNotFoundError("Battery does not exist")
                if battery["vehicle_id"] != vehicle_id:
                    raise BatteryVehicleMismatchError("Battery belongs to another vehicle")
            try:
                work_order_id = WorkOrderRepository(connection).create(
                    work_order_no, vehicle_id, reported_symptom, report_source,
                    battery_id=battery_id, report_source_note=report_source_note,
                    received_at=received_at, notes=notes,
                )
            except pymysql.IntegrityError as exc:
                # 本次插入不指定主键；当前表中另一个唯一键只有 uq_work_order_no。
                # 不解析或记录驱动原始错误文本。
                if exc.args and exc.args[0] == 1062:
                    raise DuplicateWorkOrderError("Work order number already exists") from None
                raise
            committing = True
            connection.commit()
            committed = True
        except WorkOrderError as exc:
            error = exc
        except Exception:
            if committing:
                error = WorkOrderCommitUnknownError(
                    "Work order commit outcome is unknown; verify by work order number before retrying"
                )
            else:
                error = WorkOrderPersistenceError("Work order database operation failed")
        finally:
            # 执行中断时也要清理；清理失败不能掩盖原始错误，
            # 也不能阻止其他清理步骤继续尝试。
            if not committed:
                try:
                    connection.rollback()
                except Exception:
                    rollback_failed = True
            try:
                connection.close()
            except Exception:
                close_failed = True

        if error is not None:
            error.rollback_failed = rollback_failed
            error.close_failed = close_failed
            raise error from None
        if close_failed:
            raise WorkOrderCleanupError(work_order_id) from None
        return work_order_id

    def get_by_id(self, work_order_id: int) -> dict:
        return self._read("get_by_id", work_order_id)

    def get_by_number(self, work_order_no: str) -> dict:
        return self._read("get_by_number", work_order_no)

    def _read(self, method: str, value) -> dict:
        try:
            connection = self.connection_factory()
        except (DatabaseConfigError, DatabaseConnectionError):
            raise
        except Exception:
            raise WorkOrderPersistenceError("Could not open work order connection") from None
        error = None
        rollback_failed = close_failed = False
        try:
            row = getattr(WorkOrderRepository(connection), method)(value)
            if row is None:
                error = WorkOrderNotFoundError("Work order does not exist")
        except Exception:
            error = WorkOrderPersistenceError("Could not read work order")
        finally:
            # 查询结束后也要结束读事务；不复用连接或事务快照。
            try:
                connection.rollback()
            except Exception:
                rollback_failed = True
            try:
                connection.close()
            except Exception:
                close_failed = True
        if error is None and (rollback_failed or close_failed):
            error = WorkOrderPersistenceError("Could not finish work order read")
        if error is not None:
            error.rollback_failed = rollback_failed
            error.close_failed = close_failed
            raise error from None
        return row
