-- Day 11 learning script, MySQL 8.0.16+.
-- Read docs/day11-mysql-lab.md first. Execute one statement at a time.
-- STOP on any error. Never run this against an existing practice database.
-- DDL is not undone by ROLLBACK. No DROP, overwrite, or IF NOT EXISTS.
CREATE DATABASE ebike_ai_day11
    CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_as_cs;

USE ebike_ai_day11;
SET SESSION time_zone = '+00:00';
SET SESSION sql_mode = 'STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION';

CREATE TABLE vehicle (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    vehicle_code VARCHAR(32) NOT NULL,
    brand VARCHAR(100) NULL,
    model VARCHAR(100) NULL,
    notes TEXT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    CONSTRAINT uq_vehicle_code UNIQUE (vehicle_code),
    CONSTRAINT ck_vehicle_code CHECK (CHAR_LENGTH(TRIM(vehicle_code)) > 0)
) ENGINE=InnoDB;

CREATE TABLE battery (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    battery_code VARCHAR(32) NOT NULL,
    vehicle_id BIGINT UNSIGNED NOT NULL,
    chemistry VARCHAR(50) NULL,
    nominal_voltage_v DECIMAL(10,3) NULL,
    nominal_capacity_ah DECIMAL(10,3) NULL,
    specification_note TEXT NULL,
    source_type VARCHAR(32) NOT NULL,
    source_note TEXT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    CONSTRAINT uq_battery_code UNIQUE (battery_code),
    KEY ix_battery_vehicle_history (vehicle_id, created_at, id),
    CONSTRAINT fk_battery_vehicle FOREIGN KEY (vehicle_id)
        REFERENCES vehicle (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT ck_battery_code CHECK (CHAR_LENGTH(TRIM(battery_code)) > 0),
    CONSTRAINT ck_battery_voltage CHECK (
        nominal_voltage_v IS NULL OR nominal_voltage_v >= 0
    ),
    CONSTRAINT ck_battery_capacity CHECK (
        nominal_capacity_ah IS NULL OR nominal_capacity_ah >= 0
    ),
    CONSTRAINT ck_battery_source CHECK (source_type IN (
        'NAMEPLATE', 'CUSTOMER_STATEMENT', 'TECHNICIAN_OBSERVATION',
        'HISTORICAL_RECOLLECTION', 'IMPORTED_RECORD', 'OTHER'
    ))
) ENGINE=InnoDB;

CREATE TABLE work_order (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    work_order_no VARCHAR(32) NOT NULL,
    vehicle_id BIGINT UNSIGNED NOT NULL,
    battery_id BIGINT UNSIGNED NULL,
    reported_symptom TEXT NOT NULL,
    report_source VARCHAR(32) NOT NULL,
    report_source_note TEXT NULL,
    status VARCHAR(32) NOT NULL,
    completion_outcome VARCHAR(32) NULL,
    received_at DATETIME(6) NULL,
    completed_at DATETIME(6) NULL,
    cancel_reason TEXT NULL,
    notes TEXT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    CONSTRAINT uq_work_order_no UNIQUE (work_order_no),
    KEY ix_work_order_vehicle_history (vehicle_id, received_at, id),
    KEY ix_work_order_status_created (status, created_at, id),
    KEY ix_work_order_battery_history (battery_id, received_at, id),
    CONSTRAINT fk_work_order_vehicle FOREIGN KEY (vehicle_id)
        REFERENCES vehicle (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_work_order_battery FOREIGN KEY (battery_id)
        REFERENCES battery (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT ck_work_order_no CHECK (CHAR_LENGTH(TRIM(work_order_no)) > 0),
    CONSTRAINT ck_work_order_symptom CHECK (CHAR_LENGTH(TRIM(reported_symptom)) > 0),
    CONSTRAINT ck_work_order_source CHECK (report_source IN (
        'CUSTOMER_STATEMENT', 'TECHNICIAN_OBSERVATION',
        'HISTORICAL_RECOLLECTION', 'IMPORTED_RECORD', 'OTHER'
    )),
    CONSTRAINT ck_work_order_status CHECK (status IN (
        'RECEIVED', 'INSPECTING', 'DIAGNOSING', 'REPAIRING',
        'VERIFYING', 'COMPLETED', 'CANCELLED'
    )),
    CONSTRAINT ck_work_order_outcome CHECK (
        completion_outcome IS NULL OR completion_outcome IN (
            'REPAIRED', 'PARTIAL', 'UNRESOLVED', 'NO_FAULT_FOUND'
        )
    ),
    -- Explicit IS NOT NULL prevents UNKNOWN from passing CHECK.
    CONSTRAINT ck_work_order_completion CHECK (
        (status = 'COMPLETED' AND completion_outcome IS NOT NULL)
        OR (status <> 'COMPLETED' AND completion_outcome IS NULL)
    )
) ENGINE=InnoDB;

SHOW CREATE TABLE vehicle;
SHOW CREATE TABLE battery;
SHOW CREATE TABLE work_order;
SHOW INDEX FROM battery;
SHOW INDEX FROM work_order;
