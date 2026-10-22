-- 手动实验：在同一个交互会话中，按编号顺序执行各组语句。
-- 先预测每条语句的结果，再逐项对照实验检查清单。
-- 本脚本不是自动测试程序；执行到结尾不代表全部通过。
-- 检查 DDL 后，仅在第 11 天创建的三张空表上运行。
-- 结果与预期不符时，先执行 ROLLBACK，再停止并排查。
-- 以下记录均为虚构练习数据，不能据此得出真实维修或安全结论。

-- 00：开始前核对目标库和空表状态；三张表的记录数都必须为 0。
USE ebike_ai_day11;
SELECT DATABASE(), VERSION();
SELECT 'vehicle' AS table_name, COUNT(*) AS row_count FROM vehicle
UNION ALL SELECT 'battery', COUNT(*) FROM battery
UNION ALL SELECT 'work_order', COUNT(*) FROM work_order;
SET SESSION time_zone = '+00:00';
SET SESSION sql_mode = 'STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION';
START TRANSACTION;

-- 01：创建两辆虚构车辆；未知的品牌和型号保留为 NULL。
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

-- 02：同一辆车两次进店；第二次未关联电池，接车时间未知。
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
-- 预期恰好返回两条记录，未知字段仍为 NULL。
SELECT battery_code, nominal_voltage_v, nominal_capacity_ah
FROM battery ORDER BY id;
-- 预期返回两块电池，未知规格为 NULL，不编造测量值。

-- 每个异常用例都使用保存点隔离，即使非法数据意外被接受，也能撤销该用例。
-- 03：重复业务编号；每条语句都应失败，错误码为 1062。
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

-- 04：关联记录不存在；每条语句都应返回 1452（本实验从空表开始，ID 0 不存在）。
SAVEPOINT negative_case;
UPDATE battery SET vehicle_id = 0 WHERE id = @b1;
ROLLBACK TO SAVEPOINT negative_case;
SAVEPOINT negative_case;
UPDATE work_order SET vehicle_id = 0 WHERE id = @wo1;
ROLLBACK TO SAVEPOINT negative_case;
SAVEPOINT negative_case;
UPDATE work_order SET battery_id = 0 WHERE id = @wo1;
ROLLBACK TO SAVEPOINT negative_case;

-- 05：电池规格为负数；每条语句都应返回 3819。
SAVEPOINT negative_case;
UPDATE battery SET nominal_voltage_v = -0.001 WHERE id = @b1;
ROLLBACK TO SAVEPOINT negative_case;
SAVEPOINT negative_case;
UPDATE battery SET nominal_capacity_ah = -0.001 WHERE id = @b1;
ROLLBACK TO SAVEPOINT negative_case;
-- 0 是允许存储的数值，但不代表未知；预期本次更新成功。
SAVEPOINT zero_case;
UPDATE battery SET nominal_voltage_v = 0, nominal_capacity_ah = 0 WHERE id = @b1;
SELECT nominal_voltage_v, nominal_capacity_ah FROM battery WHERE id = @b1;
ROLLBACK TO SAVEPOINT zero_case;

-- 06：非法枚举值、必填值缺失，以及仅含空格的故障描述。
SAVEPOINT negative_case;
UPDATE work_order SET status = 'BROKEN' WHERE id = @wo1; -- 3819
ROLLBACK TO SAVEPOINT negative_case;
SAVEPOINT negative_case;
UPDATE work_order SET status = 'received' WHERE id = @wo1; -- 预期 3819：枚举值区分大小写。
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

-- 07：工单状态与完工结果不一致；每条语句都应返回 3819。
SAVEPOINT negative_case;
UPDATE work_order SET status = 'COMPLETED', completion_outcome = NULL WHERE id = @wo1;
ROLLBACK TO SAVEPOINT negative_case;
SAVEPOINT negative_case;
UPDATE work_order SET completion_outcome = 'REPAIRED' WHERE id = @wo1;
ROLLBACK TO SAVEPOINT negative_case;
SAVEPOINT negative_case;
UPDATE work_order SET status = 'COMPLETED', completion_outcome = 'MAGIC' WHERE id = @wo1;
ROLLBACK TO SAVEPOINT negative_case;
-- 记录字段符合约束，不代表真实维修流程已经完成。
SAVEPOINT completion_case;
UPDATE work_order SET status = 'COMPLETED', completion_outcome = 'UNRESOLVED',
    notes = 'FICTIONAL historical import; exact completion time unknown'
WHERE id = @wo2;
SELECT status, completion_outcome, completed_at FROM work_order WHERE id = @wo2;
ROLLBACK TO SAVEPOINT completion_case;

-- 08：限制删除；另建一辆已有工单但未关联电池的车辆进行验证。
SAVEPOINT deletion_case;
INSERT INTO vehicle (vehicle_code) VALUES ('LAB-V-DELETE');
SET @vd = LAST_INSERT_ID();
INSERT INTO work_order (work_order_no, vehicle_id, reported_symptom, report_source, status)
VALUES ('LAB-WO-DELETE', @vd, 'FICTIONAL', 'OTHER', 'RECEIVED');
DELETE FROM vehicle WHERE id = @vd; -- 预期 1451：专门验证外键 fk_work_order_vehicle。
ROLLBACK TO SAVEPOINT deletion_case;
SAVEPOINT negative_case;
DELETE FROM battery WHERE id = @b1; -- 预期 1451：验证外键 fk_work_order_battery。
ROLLBACK TO SAVEPOINT negative_case;
SAVEPOINT negative_case;
DELETE FROM vehicle WHERE id = @v2; -- 预期 1451：验证外键 fk_battery_vehicle。
ROLLBACK TO SAVEPOINT negative_case;

-- 09：已知业务缺口；普通外键允许工单关联其他车辆的电池。
SAVEPOINT business_gap;
UPDATE work_order SET battery_id = @b2 WHERE id = @wo1;
SELECT w.work_order_no, w.vehicle_id AS order_vehicle,
       b.vehicle_id AS battery_vehicle,
       (w.vehicle_id = b.vehicle_id) AS same_vehicle
FROM work_order AS w JOIN battery AS b ON b.id = w.battery_id
WHERE w.id = @wo1;
-- 预期返回一条记录，same_vehicle = 0；后续 Service 必须拒绝这种关联。
ROLLBACK TO SAVEPOINT business_gap;

-- 10：整个验证会话中不执行 COMMIT 或 DDL。
ROLLBACK;
SELECT 'vehicle' AS table_name, COUNT(*) AS row_count FROM vehicle
UNION ALL SELECT 'battery', COUNT(*) FROM battery
UNION ALL SELECT 'work_order', COUNT(*) FROM work_order;
-- 预期三张表的记录数都为 0；回滚后 AUTO_INCREMENT 计数器不一定重置。
