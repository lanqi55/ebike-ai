"""Real MySQL only: guarded practice database, read-only preflight, rollback cleanup."""

from uuid import uuid4

import pymysql
import pytest

from ebike_ai.repositories.vehicle import VehicleRepository


pytestmark = [pytest.mark.integration, pytest.mark.db]


@pytest.fixture
def vehicle_db(db_connection_factory):
    connection = db_connection_factory()
    # Do not write until the real database matches the lab's essential contract.
    with connection.cursor() as cursor:
        cursor.execute("SELECT DATABASE() AS name, @@session.time_zone AS tz, @@session.sql_mode AS mode")
        session = cursor.fetchone()
        assert session["name"] == "ebike_ai_day11"
        assert session["tz"] == "+00:00"
        assert "STRICT_TRANS_TABLES" in session["mode"].split(",")
        cursor.execute(
            "SELECT ENGINE, TABLE_COLLATION FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'vehicle'"
        )
        assert cursor.fetchone() == {"ENGINE": "InnoDB", "TABLE_COLLATION": "utf8mb4_0900_as_cs"}
        cursor.execute(
            "SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, EXTRA FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'vehicle' ORDER BY ORDINAL_POSITION"
        )
        columns = cursor.fetchall()
        assert [(c["COLUMN_NAME"], c["COLUMN_TYPE"], c["IS_NULLABLE"]) for c in columns] == [
            ("id", "bigint unsigned", "NO"), ("vehicle_code", "varchar(32)", "NO"),
            ("brand", "varchar(100)", "YES"), ("model", "varchar(100)", "YES"),
            ("notes", "text", "YES"), ("created_at", "datetime(6)", "NO"),
            ("updated_at", "datetime(6)", "NO"),
        ]
        assert "auto_increment" in columns[0]["EXTRA"]
        cursor.execute(
            "SELECT CONSTRAINT_NAME, CONSTRAINT_TYPE, ENFORCED "
            "FROM information_schema.TABLE_CONSTRAINTS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'vehicle'"
        )
        constraints = {(c["CONSTRAINT_NAME"], c["CONSTRAINT_TYPE"], c["ENFORCED"]) for c in cursor.fetchall()}
        assert {("PRIMARY", "PRIMARY KEY", "YES"), ("uq_vehicle_code", "UNIQUE", "YES"),
                ("ck_vehicle_code", "CHECK", "YES")} <= constraints
    return connection


def new_code():
    return "D12" + uuid4().hex[:29]


def test_create_and_query_with_quotes_and_null(vehicle_db):
    repository = VehicleRepository(vehicle_db)
    code = new_code()
    text = "O'Brien'); DROP TABLE vehicle; --"
    vehicle_id = repository.create(code, brand=text, notes="测试备注，不是真实车辆")
    row = repository.get_by_id(vehicle_id)
    assert row["id"] == vehicle_id
    assert row["vehicle_code"] == code
    assert row["brand"] == text
    assert row["model"] is None
    assert row["notes"] == "测试备注，不是真实车辆"
    assert row["created_at"] is not None and row["updated_at"] is not None


def test_missing_id_returns_none(vehicle_db):
    # A negative ID cannot exist in the lab's UNSIGNED primary key.
    assert VehicleRepository(vehicle_db).get_by_id(-1) is None


def test_duplicate_code_reports_unique_constraint(vehicle_db):
    repository = VehicleRepository(vehicle_db)
    code = new_code()
    repository.create(code)
    with pytest.raises(pymysql.IntegrityError) as error:
        repository.create(code)
    assert error.value.args[0] == 1062
    assert "uq_vehicle_code" in error.value.args[1]


def test_rollback_is_visible_from_a_new_connection(vehicle_db, db_connection_factory):
    repository = VehicleRepository(vehicle_db)
    vehicle_id = repository.create(new_code())
    assert repository.get_by_id(vehicle_id) is not None
    vehicle_db.rollback()
    other_connection = db_connection_factory()
    assert VehicleRepository(other_connection).get_by_id(vehicle_id) is None
