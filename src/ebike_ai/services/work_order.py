"""Create an order for an existing vehicle using one fresh transaction."""

from collections.abc import Callable
from datetime import datetime

from ebike_ai.database import (
    DatabaseConfig, DatabaseConfigError, DatabaseConnectionError, connect_database,
)
from ebike_ai.repositories.battery import BatteryRepository
from ebike_ai.repositories.vehicle import VehicleRepository
from ebike_ai.repositories.work_order import WorkOrderRepository


class WorkOrderError(RuntimeError):
    """Public errors contain fixed messages, never driver messages or inputs."""

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


class WorkOrderCommitUnknownError(WorkOrderPersistenceError):
    """A failed commit response does not establish whether MySQL committed."""


class WorkOrderCleanupError(WorkOrderError):
    """Commit succeeded, but closing failed; callers must not recreate the order."""

    def __init__(self, work_order_id: int):
        super().__init__("Work order committed, but connection close failed; do not retry creation")
        self.work_order_id = work_order_id
        self.close_failed = True


def _open_connection():
    return connect_database(DatabaseConfig.from_env())


class WorkOrderService:
    def __init__(self, connection_factory: Callable = _open_connection):
        # Factories must return a NEW connection with autocommit=False each time.
        self.connection_factory = connection_factory

    def create_work_order(
        self, work_order_no: str, vehicle_id: int, reported_symptom: str,
        report_source: str, *, battery_id: int | None = None,
        report_source_note: str | None = None, received_at: datetime | None = None,
        notes: str | None = None,
    ) -> int:
        """Validate ownership, insert and commit; no retry on any failure."""
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
            work_order_id = WorkOrderRepository(connection).create(
                work_order_no, vehicle_id, reported_symptom, report_source,
                battery_id=battery_id, report_source_note=report_source_note,
                received_at=received_at, notes=notes,
            )
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
            # Cleanup also runs on interruption. A cleanup failure must not hide
            # the primary failure, or prevent the other cleanup attempt.
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
