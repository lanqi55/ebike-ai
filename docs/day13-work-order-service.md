# 第 13 天：最小建单 Service 与业务规则测试

目标：为已有车辆创建一张 `RECEIVED` 工单，拒绝不存在的车辆、电池及跨车辆电池关联。沿用 Day 11 的三张表与 Day 12 的 PyMySQL 连接，不改表、不增加依赖、不接 API。

## 1. 先预测，再读代码

按下面顺序阅读，每一步先口头预测行为，再查看实现与测试：

1. Repository：电池查询失败或工单插入成功时，谁决定提交、回滚和关闭连接？
2. Service：车辆存在、电池属于其他车辆时，哪些 SQL 应执行，哪些不应执行？
3. 失败测试：插入成功但提交时断线，能否断定记录不存在？回滚本身失败后，还应尝试什么？

本聊天已确认：用户能说明多次写入应在同一连接、同一未提交事务中统一撤销；能判断电池归属、允许未指定电池，以及校验失败不得建单；能说明写入失败应回滚、关闭连接，不能返回成功。“同事务能读到不代表已提交”经过讲解，不记作首次独立掌握。参数化 SQL、NULL/CHECK、真假数据库测试边界等尚未完整复述，不标记 Day 12 全部学习验收通过。

## 2. 从 SQL 到业务

| 模块 | 职责 |
|---|---|
| [VehicleRepository](../src/ebike_ai/repositories/vehicle.py) | 复用现有车辆查询 |
| [BatteryRepository](../src/ebike_ai/repositories/battery.py) | 参数化查询电池 ID、所属车辆 ID，带 `FOR UPDATE` |
| [WorkOrderRepository](../src/ebike_ai/repositories/work_order.py) | 参数化插入，初始状态为 `RECEIVED`，三个完工字段为空 |
| [WorkOrderService](../src/ebike_ai/services/work_order.py) | 校验关联、组织单次事务、提交与清理、提供稳定错误 |

Repository 均接收调用方的连接，不创建连接，不提交、回滚或关闭连接。电池查询的行锁用于保护“读取归属到提交工单”这一段；本轮只验证 SQL 请求了锁，没有实测并发阻塞，也没有实现电池转移业务或保证提交后归属永不变化。

Service 默认工厂在调用时读取数据库配置并新建连接；实例化 Service 不连接数据库。注入的工厂必须每次提供独占的新连接，且 `autocommit=False`，不能返回共享连接或已有业务事务。每次建单的 Repository 共用这一条连接。

调用接口为：

```python
create_work_order(
    work_order_no, vehicle_id, reported_symptom, report_source,
    *, battery_id=None, report_source_note=None, received_at=None, notes=None,
) -> int
```

- `work_order_no` 由调用方提供；唯一性、文本非空和来源允许值沿用现有数据库约束。
- `battery_id=None` 表示未指定；`0` 等其他值仍会查询，不能被当作未填写。
- 来源必须明确传入，不自动把客户描述当成维修师确认。
- `received_at` 使用不带时区的 UTC `datetime`，未知时为 `None`，不以当前时间补造。当前内部接口要求调用方遵守这一约定；未来 API 入参校验另做。
- 成功返回内部工单 ID，只有 `commit()` 正常返回后才视为已提交。

本轮没有新增车辆并建单、工单查询 API、状态流转、人工审核、重试或幂等协议。

## 3. 分支与失败含义

| 场景 | 行为 |
|---|---|
| 车辆不存在 | `VehicleNotFoundError`；不查询电池、不插入、不提交 |
| 未指定电池 | 跳过电池查询，插入后提交 |
| 指定电池不存在 | `BatteryNotFoundError`；不插入、不提交 |
| 电池属于其他车辆 | `BatteryVehicleMismatchError`；不插入、不提交 |
| 车辆与电池匹配 | 插入后提交，再关闭连接 |
| 查询或插入失败 | `WorkOrderPersistenceError`；尝试回滚并关闭 |
| 提交异常 | `WorkOrderCommitUnknownError`；尝试回滚并关闭，提交结果仍未知 |
| 提交成功但关闭失败 | `WorkOrderCleanupError`；携带已保存的 `work_order_id`，不回滚、不再次建单 |

业务错误与数据库操作错误都执行清理。错误对象的 `rollback_failed`、`close_failed` 只记录清理是否失败，不包含底层异常文本；清理错误不覆盖原始业务错误。未能创建连接时无连接可供清理；现有安全的配置/连接错误保持原类型，其余工厂错误转为固定提示。

提交异常可能是“服务端已经提交，但客户端没有收到响应”，所以即使随后调用回滚也不能断言未保存。当前不自动重试；调用方需要凭原工单编号核对数据库实际结果，再决定处理方式。没有实现自动核对或恢复流程。

## 4. 离线验证

在仓库根目录的新 PowerShell 终端执行：

```powershell
Remove-Item Env:DASHSCOPE_API_KEY -ErrorAction SilentlyContinue
Remove-Item Env:PYTEST_ADDOPTS -ErrorAction SilentlyContinue
.\venv\Scripts\python.exe -m pytest test_cases/test_database.py test_cases/test_work_order_repositories.py test_cases/test_work_order_service.py -q
.\venv\Scripts\python.exe -m pytest -q -rs --junitxml=reports/day13/junit.xml
.\venv\Scripts\python.exe -m pip check
```

逐条执行；失败先停止定位。若使用 `.venv`，替换解释器目录。没有 `--run-live` 和 `--run-db`，不运行真实模型或真实数据库测试。

新增 27 条单元测试：6 条 Repository SQL 契约、21 条 Service 行为测试。Service 测试使用真实 Repository 配合假连接，检查同一连接上的 SQL、事务顺序、非法关联零插入、空电池跳过查询、字段传递、每次调用新连接、异常脱敏与清理失败。插入和提交失败分别模拟，另覆盖中断时清理。

这些测试证明代码的分支与调用契约，不能证明 MySQL 接受新 SQL、提交持久化或真实锁行为。Day 12 的 4 条真实数据库用例只覆盖车辆 Repository，不能替代今天的新建单链路验证。

## 5. 验收记录（2026-10-18）

- 定向测试：43 passed，1 条既有 LangChain 弃用警告，0.24 秒。
- `pip check`：通过，无声明依赖冲突。
- 完整离线回归：115 passed、6 skipped、2 条既有弃用警告，105.70 秒。2 条真实模型和 4 条真实 MySQL 测试未开启；JUnit 保存在已忽略的 `reports/day13/junit.xml`。
- 未连接真实 MySQL、未调用真实模型，未新增生产依赖或修改数据库结构。
- 下一步：独立解释 Repository/Service 分工及提交结果未知场景，再准备显式的真实建单集成验证；不要直接把假连接测试称为数据库验收。
