-- Manual lab: execute numbered blocks in order in ONE interactive session.
-- Predict each result first. Match EVERY result against the lab checklist.
-- This is NOT an automated test runner; reaching the end does not mean PASS.
-- Only run on the three EMPTY Day 11 tables after inspecting their DDL.
-- On an unexpected result: ROLLBACK; stop and investigate.
-- All records below are FICTIONAL. No real repair / safety conclusions.

-- 00: Check target and empty tables BEFORE starting; all counts must be 0.
USE ebike_ai_day11;
SELECT DATABASE(), VERSION();
SELECT 'vehicle' AS table_name, COUNT(*) AS row_count FROM vehicle
UNION ALL SELECT 'battery', COUNT(*) FROM battery
UNION ALL SELECT 'work_order', COUNT(*) FROM work_order;
SET SESSION time_zone = '+00:00';
SET SESSION sql_mode = 'STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION';
START TRANSACTION;

-- 01: Two fictional vehicles; unknown brand/model remain NULL.
INSERT INTO vehicle (vehicle_code, notes) VALUES ('LAB-V-001', 'FICTIONAL Day 11');
SET @v1 = LAST_INSERT_ID();
INSERT INTO vehicle (vehicle_code, notes) VALUES ('LAB-V-002', 'FICTIONAL Day 11');
SET @v2 = LAST_INSERT_ID();
INSERT INTO battery (battery_code, vehicle_id, source_type, source_note)
VALUES ('LAB-B-001', @v1, 'OTHER', 'FICTIONAL; specifications unknown');
SET @b1 = LAST_INSERT_ID();
INSERT INTO battery (battery_code, vehicle_id, source_type, source_note)
VALUES ('LAB-B-002', @v2, 'OTHER', 'FICTIONAL; specifications unknown');
SET @b2 = LAST_INSERT_ID();

-- 02: One vehicle, two visits; second visit has no battery or known date.
INSERT INTO work_order (
    work_order_no, vehicle_id, battery_id, reported_symptom, report_source,
    report_source_note, status, received_at
) VALUES (
    'LAB-WO-001', @v1, @b1, '虚构练习：灯不亮', 'OTHER',
    'FICTIONAL Day 11', 'RECEIVED', '2026-10-01 02:00:00'
);
SET @wo1 = LAST_INSERT_ID();
INSERT INTO work_order (
    work_order_no, vehicle_id, reported_symptom, report_source, status, notes
) VALUES ('LAB-WO-002', @v1, '虚构练习：喇叭不响', 'OTHER', 'RECEIVED', 'FICTIONAL Day 11');
SET @wo2 = LAST_INSERT_ID();
SELECT v.vehicle_code, v.brand, w.work_order_no, w.battery_id, w.received_at
FROM vehicle AS v JOIN work_order AS w ON w.vehicle_id = v.id
WHERE v.id = @v1 ORDER BY w.received_at, w.id;
-- Expect exactly two rows, with NULLs preserved.
SELECT battery_code, nominal_voltage_v, nominal_capacity_ah
FROM battery ORDER BY id;
-- Expect two batteries with NULL specifications, not fictional measurements.

-- Each negative test uses a savepoint to isolate even an unexpected acceptance.
-- 03: Duplicate business codes: each must fail with 1062.
SAVEPOINT negative_case;
INSERT INTO vehicle (vehicle_code) VALUES ('LAB-V-001');
ROLLBACK TO SAVEPOINT negative_case;
SAVEPOINT negative_case;
INSERT INTO battery (battery_code, vehicle_id, source_type)
VALUES ('LAB-B-001', @v1, 'OTHER');
ROLLBACK TO SAVEPOINT negative_case;
SAVEPOINT negative_case;
INSERT INTO work_order (work_order_no, vehicle_id, reported_symptom, report_source, status)
VALUES ('LAB-WO-001', @v1, 'FICTIONAL', 'OTHER', 'RECEIVED');
ROLLBACK TO SAVEPOINT negative_case;

-- 04: Missing parents: each must fail with 1452 (0 absent in empty-start lab).
SAVEPOINT negative_case;
UPDATE battery SET vehicle_id = 0 WHERE id = @b1;
ROLLBACK TO SAVEPOINT negative_case;
SAVEPOINT negative_case;
UPDATE work_order SET vehicle_id = 0 WHERE id = @wo1;
ROLLBACK TO SAVEPOINT negative_case;
SAVEPOINT negative_case;
UPDATE work_order SET battery_id = 0 WHERE id = @wo1;
ROLLBACK TO SAVEPOINT negative_case;

-- 05: Negative specifications: each must fail with 3819.
SAVEPOINT negative_case;
UPDATE battery SET nominal_voltage_v = -0.001 WHERE id = @b1;
ROLLBACK TO SAVEPOINT negative_case;
SAVEPOINT negative_case;
UPDATE battery SET nominal_capacity_ah = -0.001 WHERE id = @b1;
ROLLBACK TO SAVEPOINT negative_case;
-- 0 is a valid stored number, not a substitute for unknown; expect success.
SAVEPOINT zero_case;
UPDATE battery SET nominal_voltage_v = 0, nominal_capacity_ah = 0 WHERE id = @b1;
SELECT nominal_voltage_v, nominal_capacity_ah FROM battery WHERE id = @b1;
ROLLBACK TO SAVEPOINT zero_case;

-- 06: Invalid codes / missing required value / blank symptom.
SAVEPOINT negative_case;
UPDATE work_order SET status = 'BROKEN' WHERE id = @wo1; -- 3819
ROLLBACK TO SAVEPOINT negative_case;
SAVEPOINT negative_case;
UPDATE work_order SET status = 'received' WHERE id = @wo1; -- 3819: case sensitive
ROLLBACK TO SAVEPOINT negative_case;
SAVEPOINT negative_case;
UPDATE battery SET source_type = 'AI_GUESS' WHERE id = @b1; -- 3819
ROLLBACK TO SAVEPOINT negative_case;
SAVEPOINT negative_case;
UPDATE work_order SET report_source = 'AI_GUESS' WHERE id = @wo1; -- 3819
ROLLBACK TO SAVEPOINT negative_case;
SAVEPOINT negative_case;
UPDATE work_order SET reported_symptom = NULL WHERE id = @wo1; -- 1048
ROLLBACK TO SAVEPOINT negative_case;
SAVEPOINT negative_case;
UPDATE work_order SET reported_symptom = '   ' WHERE id = @wo1; -- 3819
ROLLBACK TO SAVEPOINT negative_case;

-- 07: Status/outcome consistency: each must fail with 3819.
SAVEPOINT negative_case;
UPDATE work_order SET status = 'COMPLETED', completion_outcome = NULL WHERE id = @wo1;
ROLLBACK TO SAVEPOINT negative_case;
SAVEPOINT negative_case;
UPDATE work_order SET completion_outcome = 'REPAIRED' WHERE id = @wo1;
ROLLBACK TO SAVEPOINT negative_case;
SAVEPOINT negative_case;
UPDATE work_order SET status = 'COMPLETED', completion_outcome = 'MAGIC' WHERE id = @wo1;
ROLLBACK TO SAVEPOINT negative_case;
-- Valid row shape; not evidence that the real repair workflow is complete.
SAVEPOINT completion_case;
UPDATE work_order SET status = 'COMPLETED', completion_outcome = 'UNRESOLVED',
    notes = 'FICTIONAL historical import; exact completion time unknown'
WHERE id = @wo2;
SELECT status, completion_outcome, completed_at FROM work_order WHERE id = @wo2;
ROLLBACK TO SAVEPOINT completion_case;

-- 08: Restrict deletion: use a separate vehicle with a work order but no battery.
SAVEPOINT deletion_case;
INSERT INTO vehicle (vehicle_code) VALUES ('LAB-V-DELETE');
SET @vd = LAST_INSERT_ID();
INSERT INTO work_order (work_order_no, vehicle_id, reported_symptom, report_source, status)
VALUES ('LAB-WO-DELETE', @vd, 'FICTIONAL', 'OTHER', 'RECEIVED');
DELETE FROM vehicle WHERE id = @vd; -- 1451: specifically fk_work_order_vehicle
ROLLBACK TO SAVEPOINT deletion_case;
SAVEPOINT negative_case;
DELETE FROM battery WHERE id = @b1; -- 1451: fk_work_order_battery
ROLLBACK TO SAVEPOINT negative_case;
SAVEPOINT negative_case;
DELETE FROM vehicle WHERE id = @v2; -- 1451: fk_battery_vehicle
ROLLBACK TO SAVEPOINT negative_case;

-- 09: Known business gap: ordinary FKs ACCEPT another vehicle's battery.
SAVEPOINT business_gap;
UPDATE work_order SET battery_id = @b2 WHERE id = @wo1;
SELECT w.work_order_no, w.vehicle_id AS order_vehicle,
       b.vehicle_id AS battery_vehicle,
       (w.vehicle_id = b.vehicle_id) AS same_vehicle
FROM work_order AS w JOIN battery AS b ON b.id = w.battery_id
WHERE w.id = @wo1;
-- Expect one row, same_vehicle = 0. Future Service must reject this association.
ROLLBACK TO SAVEPOINT business_gap;

-- 10: No COMMIT or DDL anywhere in this verification session.
ROLLBACK;
SELECT 'vehicle' AS table_name, COUNT(*) AS row_count FROM vehicle
UNION ALL SELECT 'battery', COUNT(*) FROM battery
UNION ALL SELECT 'work_order', COUNT(*) FROM work_order;
-- Expect three zeros. AUTO_INCREMENT counters need not reset after rollback.
