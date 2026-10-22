"""Opt-in committed-data lab. Never import credentials or connect at import time."""

import json
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from ebike_ai.database import connect_database


TABLE_KEYS = {"vehicle": "vehicle_code", "battery": "battery_code", "work_order": "work_order_no"}
REQUIRED_COLUMNS = {
    "vehicle": "id vehicle_code brand model notes created_at updated_at",
    "battery": "id battery_code vehicle_id chemistry nominal_voltage_v nominal_capacity_ah "
               "specification_note source_type source_note created_at updated_at",
    "work_order": "id work_order_no vehicle_id battery_id reported_symptom report_source "
                  "report_source_note status completion_outcome received_at completed_at "
                  "cancel_reason notes created_at updated_at",
}
CHECKS = {
    "vehicle": {"ck_vehicle_code"},
    "battery": {"ck_battery_code", "ck_battery_voltage", "ck_battery_capacity", "ck_battery_source"},
    "work_order": {"ck_work_order_no", "ck_work_order_symptom", "ck_work_order_source",
                   "ck_work_order_status", "ck_work_order_outcome", "ck_work_order_completion"},
}


def preflight(connection):
    """Read-only guard; mismatch stops the lab rather than repairing its schema."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT DATABASE() AS name, @@session.time_zone AS tz, @@session.sql_mode AS mode")
        session = cursor.fetchone()
        assert session["name"] == "ebike_ai_day11", "Wrong practice database"
        assert session["tz"] == "+00:00", "UTC session required"
        assert "STRICT_TRANS_TABLES" in session["mode"].split(","), "Strict SQL mode required"
        for table, key in TABLE_KEYS.items():
            cursor.execute(
                "SELECT ENGINE, TABLE_COLLATION FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s", (table,),
            )
            assert cursor.fetchone() == {"ENGINE": "InnoDB", "TABLE_COLLATION": "utf8mb4_0900_as_cs"}
            cursor.execute(
                "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s", (table,),
            )
            assert set(REQUIRED_COLUMNS[table].split()) <= {r["COLUMN_NAME"] for r in cursor.fetchall()}
            cursor.execute(
                "SELECT INDEX_NAME, COLUMN_NAME, SEQ_IN_INDEX FROM information_schema.STATISTICS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND NON_UNIQUE = 0", (table,),
            )
            indexes = {}
            for row in cursor.fetchall():
                indexes.setdefault(row["INDEX_NAME"], []).append((row["SEQ_IN_INDEX"], row["COLUMN_NAME"]))
            assert sorted(indexes.get("PRIMARY", [])) == [(1, "id")]
            assert [(1, key)] in [sorted(columns) for columns in indexes.values()]
            cursor.execute(
                "SELECT CONSTRAINT_NAME FROM information_schema.TABLE_CONSTRAINTS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s "
                "AND CONSTRAINT_TYPE = 'CHECK' AND ENFORCED = 'YES'", (table,),
            )
            assert CHECKS[table] <= {r["CONSTRAINT_NAME"] for r in cursor.fetchall()}
        cursor.execute(
            "SELECT TABLE_NAME, COLUMN_NAME, REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME "
            "FROM information_schema.KEY_COLUMN_USAGE WHERE TABLE_SCHEMA = DATABASE() "
            "AND REFERENCED_TABLE_NAME IS NOT NULL"
        )
        foreign_keys = {(r["TABLE_NAME"], r["COLUMN_NAME"], r["REFERENCED_TABLE_NAME"],
                         r["REFERENCED_COLUMN_NAME"]) for r in cursor.fetchall()}
        assert {("battery", "vehicle_id", "vehicle", "id"),
                ("work_order", "vehicle_id", "vehicle", "id"),
                ("work_order", "battery_id", "battery", "id")} <= foreign_keys


def verify_owned(row, expected):
    """Refuse cleanup on an identity/content mismatch, including a known ID."""
    if any(row.get(key) != value for key, value in expected.items()):
        raise AssertionError("Lab record identity/content mismatch; cleanup stopped")


class WorkOrderLab:
    def __init__(self, settings, artifact_dir):
        if settings.database != "ebike_ai_day11":
            raise ValueError("Only ebike_ai_day11 is allowed")
        self.settings = settings
        self.run_id = "W3" + uuid4().hex[:24]
        self.manifest_path = Path(artifact_dir) / (self.run_id + ".json")
        self.connections = []
        self.owned = False
        self.records = {
            "vehicle": [{"vehicle_code": self.run_id + suffix, "notes": self.run_id} for suffix in ("VA", "VB")],
            "battery": [{"battery_code": self.run_id + suffix, "source_type": "OTHER",
                         "source_note": self.run_id} for suffix in ("BX", "BY")],
            "work_order": [{"work_order_no": self.run_id + suffix} for suffix in ("O1", "O2")],
        }

    def save_manifest(self, state):
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_text(json.dumps(
            {"run_id": self.run_id, "database": "ebike_ai_day11", "state": state,
             "records": self.records}, ensure_ascii=False, indent=2, default=str,
        ), encoding="utf-8")

    def connect(self):
        connection = connect_database(self.settings)
        self.connections.append(connection)
        return connection

    @contextmanager
    def connection(self):
        connection = self.connect()
        try:
            yield connection
        finally:
            try:
                connection.rollback()
            finally:
                connection.close()

    def prepare(self):
        with self.connection() as connection:
            preflight(connection)
            with connection.cursor() as cursor:
                for table, records in self.records.items():
                    for record in records:
                        key = TABLE_KEYS[table]
                        cursor.execute(f"SELECT id FROM {table} WHERE {key} = %s", (record[key],))
                        assert cursor.fetchone() is None, "Generated lab identifier already exists"
                self.save_manifest("reserved")  # Save exact identifiers BEFORE the first write.
                self.owned = True
                for record in self.records["vehicle"]:
                    cursor.execute("INSERT INTO vehicle (vehicle_code, notes) VALUES (%s, %s)",
                                   (record["vehicle_code"], record["notes"]))
                    record["id"] = cursor.lastrowid
                    self.save_manifest("preparing")
                for index, record in enumerate(self.records["battery"]):
                    record["vehicle_id"] = self.records["vehicle"][index]["id"]
                    self.save_manifest("preparing")
                    cursor.execute(
                        "INSERT INTO battery (battery_code, vehicle_id, source_type, source_note) "
                        "VALUES (%s, %s, %s, %s)",
                        (record["battery_code"], record["vehicle_id"], record["source_type"], record["source_note"]),
                    )
                    record["id"] = cursor.lastrowid
                    self.save_manifest("preparing")
            connection.commit()
        self.save_manifest("prepared")

    def order(self, *, index=0, **overrides):
        fields = {"work_order_no": self.records["work_order"][index]["work_order_no"],
                  "vehicle_id": self.records["vehicle"][0]["id"], "battery_id": None,
                  "reported_symptom": "灯不亮，O'Brien 的测试车", "report_source": "CUSTOMER_STATEMENT",
                  "report_source_note": None, "notes": self.run_id, "received_at": None}
        fields.update(overrides)
        self.records["work_order"][index] = {
            **fields, "status": "RECEIVED", "completion_outcome": None,
            "completed_at": None, "cancel_reason": None,
        }
        self.save_manifest("running")
        return fields

    def find_order(self, number):
        # A newly opened connection cannot reuse an older transaction snapshot.
        with self.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT * FROM work_order WHERE work_order_no = %s", (number,))
                rows = cursor.fetchall()
                assert len(rows) <= 1
                return rows[0] if rows else None

    def cleanup(self):
        # Release every surviving service/preparation connection before taking cleanup locks.
        release_failed = False
        for connection in self.connections:
            if connection.open:
                try:
                    connection.rollback()
                except Exception:
                    release_failed = True
                finally:
                    try:
                        connection.close()
                    except Exception:
                        release_failed = True
        if release_failed:
            raise AssertionError("Could not release lab connections; inspect manifest")
        if not self.owned:
            return
        with self.connection() as connection:
            preflight(connection)
            with connection.cursor() as cursor:
                # All deletions belong to one transaction; a later mismatch rolls everything back.
                for table in ("work_order", "battery", "vehicle"):
                    key = TABLE_KEYS[table]
                    for expected in self.records[table]:
                        cursor.execute(f"SELECT * FROM {table} WHERE {key} = %s FOR UPDATE", (expected[key],))
                        row = cursor.fetchone()
                        if row is None:
                            continue
                        # Reserved but never submitted order numbers are NOT owned rows.
                        if table == "work_order" and "notes" not in expected:
                            raise AssertionError("Unexpected row at unused order number; cleanup stopped")
                        verify_owned(row, expected)
                        cursor.execute(f"DELETE FROM {table} WHERE id = %s AND {key} = %s", (row["id"], expected[key]))
                        assert cursor.rowcount == 1
            connection.commit()
        with self.connection() as connection:
            with connection.cursor() as cursor:
                for table, records in self.records.items():
                    for record in records:
                        key = TABLE_KEYS[table]
                        cursor.execute(f"SELECT id FROM {table} WHERE {key} = %s", (record[key],))
                        assert cursor.fetchone() is None, "Lab cleanup left a record"
        self.save_manifest("cleaned")
