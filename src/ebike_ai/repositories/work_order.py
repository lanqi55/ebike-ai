"""Work order inserts; business checks and transactions belong to the caller."""

from datetime import datetime


class WorkOrderRepository:
    def __init__(self, connection):
        self.connection = connection

    def create(
        self, work_order_no: str, vehicle_id: int, reported_symptom: str,
        report_source: str, *, battery_id: int | None = None,
        report_source_note: str | None = None, received_at: datetime | None = None,
        notes: str | None = None,
    ) -> int:
        """Insert a RECEIVED order; received_at is naive UTC or unknown (None)."""
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
