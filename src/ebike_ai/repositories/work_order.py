"""读写工单数据；业务校验和事务由调用方负责。"""

from datetime import datetime


class WorkOrderRepository:
    def __init__(self, connection):
        self.connection = connection

    def get_by_id(self, work_order_id: int) -> dict | None:
        return self._get("id", work_order_id)

    def get_by_number(self, work_order_no: str) -> dict | None:
        return self._get("work_order_no", work_order_no)

    def _get(self, column: str, value) -> dict | None:
        # 列名只能使用白名单中的常量；查询值始终通过参数绑定传入。
        if column not in ("id", "work_order_no"):
            raise ValueError("Unsupported work order lookup")
        with self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, work_order_no, vehicle_id, battery_id, reported_symptom, "
                "report_source, report_source_note, status, completion_outcome, received_at, "
                "completed_at, cancel_reason, notes, created_at, updated_at "
                f"FROM work_order WHERE {column} = %s", (value,),
            )
            return cursor.fetchone()

    def create(
        self, work_order_no: str, vehicle_id: int, reported_symptom: str,
        report_source: str, *, battery_id: int | None = None,
        report_source_note: str | None = None, received_at: datetime | None = None,
        notes: str | None = None,
    ) -> int:
        """插入 RECEIVED 工单；received_at 为不带时区的 UTC 时间，未知时为 None。"""
        with self.connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO work_order "
                "(work_order_no, vehicle_id, battery_id, reported_symptom, "
                "report_source, report_source_note, status, received_at, notes, "
                "completion_outcome, completed_at, cancel_reason) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NULL, NULL, NULL)",
                (work_order_no, vehicle_id, battery_id, reported_symptom,
                 report_source, report_source_note, "RECEIVED", received_at, notes),
            )
            return cursor.lastrowid
