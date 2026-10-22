# 第三周：维修工单 API 与真实提交验证

本周把已有建单 Service 接到 HTTP，并验证创建后新连接可见。学习目标是讲清 API、Service、Repository、事务和测试证据的边界。测量、AI 诊断、审核、完工、前端和并发锁实验顺延；不新增依赖或修改三张练习表。

## Day 15–16：真实建单验证

先独立解释：参数化 SQL 为什么将数据与语句分开传；NULL 与 0 的区别；事务、索引、连接池各解决什么问题；为什么 rollback 无法清理已提交记录。解释卡住时先回看 [第二周复盘](day14-week2-retrospective.md)，不把代码完成算成学习掌握。

新测试使用已有 `ebike_ai_day11`，需要对 vehicle、battery、work_order 有 SELECT、INSERT、DELETE 权限，并可读取表元数据。不同于 Day 12，本次确实 COMMIT，然后新连接查询，最后精确 DELETE 并提交。只在练习库运行，不重跑建表脚本。

1. 写入前核对实际数据库、UTC、严格模式、三表字段、InnoDB、排序规则、主键/业务唯一键、外键及已启用 CHECK 的名称。不自动建表或修表；预检不代替实际约束测试，也不证明所有 CHECK 表达式与原始 DDL 完全相同。
2. 每个用例生成独立编号，预检没有同编号记录，在 `reports/week3/manifests/` 保存不含凭据的运行清单。先提交车辆 A/B 与电池 X/Y。
3. Service 独立连接提交；核对使用另一个新连接。成功场景验证字段与 ID，失败场景验证未留下工单；重复编号不得覆盖原单。
4. 无论用例成功、失败还是准备部分失败，都尝试释放连接，按准确编号、已知 ID 和内容核对，依次删除本次工单、电池、车辆并提交，再用新连接检查残留。身份不匹配时停止清理，不扩大删除范围。

进程被强制结束时 fixture 可能无法清理。保留运行清单，对照准确编号、ID、内容人工核对后清理；禁止清空表、按前缀批删、重置自增或关闭外键。清理失败属于测试失败，不能只报告测试正文通过。自增 ID 可能产生间隔。

### 本机运行

在自己的 PowerShell 中执行，密码不要发到聊天。另一个终端的环境变量不会自动传入已启动的 Codex。现有环境是 `venv`；如使用 `.venv`，替换解释器路径。

```powershell
$week3Python = ".\venv\Scripts\python.exe"
Remove-Item Env:DASHSCOPE_API_KEY -ErrorAction SilentlyContinue
Remove-Item Env:PYTEST_ADDOPTS -ErrorAction SilentlyContinue
$env:EBIKE_DB_HOST = "127.0.0.1"
$env:EBIKE_DB_PORT = "3306"
$env:EBIKE_DB_NAME = "ebike_ai_day11"
$env:EBIKE_DB_USER = Read-Host "MySQL 用户名"
$week3Secret = Read-Host "MySQL 密码" -AsSecureString
$env:EBIKE_DB_PASSWORD = [System.Net.NetworkCredential]::new("", $week3Secret).Password
Remove-Variable week3Secret
try {
    & $week3Python -m pytest test_cases/test_work_order_mysql.py --run-db -q -rs --tb=short
    if ($LASTEXITCODE -ne 0) { throw "真实建单验证未通过，请先处理失败和清理记录" }
} finally {
    Remove-Item Env:EBIKE_DB_PASSWORD -ErrorAction SilentlyContinue
}
```

预期 **6 passed**：两种成功建单、车辆缺失、电池缺失、跨车电池、重复编号。缺配置或预检不通过会报错；`6 skipped` 不代表真实验收成功。不启用 `--run-live`，不调用模型。不要启用包含局部变量的 `--showlocals` 或输出连接配置。

### 当前证据

2026-10-22：真实建单测试和独立清理 fixture 已实现；当前 Codex 进程没有数据库配置，真实 MySQL 尚未运行。离线测试验证清理边界和事务行为，不能证明 MySQL SQL、提交结果或锁等待正确。

## Day 17–19：创建、查询与错误处理

```text
HTTP 请求 → Pydantic 校验 → WorkOrderService → Repository → MySQL
HTTP 响应 ← 固定错误映射 / UTC 序列化 ← 事务完成及连接关闭
```

HTTP 层位于 [work_order_api.py](../src/ebike_ai/work_order_api.py)，以 router 接入现有 app。同步 PyMySQL 沿用同步端点；每次调用创建独立连接，Service 持有事务，Repository 不提交。查询也结束读事务、关闭连接，不复用快照。无数据库配置时 `/health`、`/docs`、`/openapi.json` 仍可使用。

| 接口 | 输入与输出 |
|---|---|
| `POST /work-orders` | 必填 work_order_no、vehicle_id、reported_symptom、report_source；可选 battery_id、report_source_note、received_at、notes。成功 201，返回 id、work_order_no、固定初始状态 RECEIVED、可空 warning |
| `GET /work-orders/{id}` | 按正整数内部 ID 查详情，不存在 404 |
| `GET /work-orders/by-number/{work_order_no}` | 按唯一业务编号查详情；编号作为 URL 路径时需要编码，包含 `/` 的编号也支持 |

业务编号去除首尾空白后为 1–32 字符；故障描述去除首尾空白后非空。请求中的 ID 必须是 JSON 正整数，不能用布尔值或数字字符串代替，上限与 BIGINT UNSIGNED 一致。来源只接受现有表中的五个枚举。文本不得超过 MySQL TEXT 的 65535 UTF-8 字节。额外字段被拒绝，不能直接提交状态或完工结果。

`received_at` 未提供或 null 表示未知，不自动补当前时间；提供时使用带时区的 ISO 8601 字符串，转换为 UTC 后存入 DATETIME。查询输出显式 UTC 时间，例如 `2026-10-22T08:30:00Z`；未知值保持 null。

| 情况 | HTTP | detail.code / 行为 |
|---|---|---|
| 请求模型校验失败 | 422 | FastAPI 标准验证错误列表，不调用 Service |
| 车辆、电池、工单不存在 | 404 | VEHICLE_NOT_FOUND / BATTERY_NOT_FOUND / WORK_ORDER_NOT_FOUND |
| 电池不属于该车 | 409 | BATTERY_VEHICLE_MISMATCH |
| 编号重复 | 409 | DUPLICATE_WORK_ORDER；不会覆盖原单，也不自动换编号 |
| 数据库配置缺失、连接失败 | 503 | DATABASE_NOT_CONFIGURED / DATABASE_UNAVAILABLE |
| 数据库读写失败 | 503 | DATABASE_OPERATION_FAILED |
| commit 响应异常 | 503 | COMMIT_OUTCOME_UNKNOWN；按原编号核对，不自动重试创建 |
| commit 成功、close 失败 | 201 | 返回已保存 ID 和 warning，不回滚、不重新创建 |
| 未预期内部错误 | 500 | INTERNAL_ERROR；固定提示，不透传驱动消息 |

除 422 外，错误体为 `{"detail":{"code":"...","message":"..."}}`。编号重复是冲突检测，并非完整幂等协议。提交结果未知时，查询不到也不能立刻断定失败或换编号重建；查询本身不可用时结果继续保持未知，需待数据库恢复后核对。

原 Day 13 的重复编号统一持久化异常已细化为 `DuplicateWorkOrderError`（仍继承 `WorkOrderPersistenceError`）；只将 INSERT 阶段的 1062 映射为编号冲突，commit 阶段的异常继续视为结果未知。当前表 INSERT 不指定主键，唯一业务约束为 uq_work_order_no；以后修改唯一键或触发器时必须复核此判断。

离线验证命令：

```powershell
.\venv\Scripts\python.exe -m pytest test_cases/test_work_order_api.py test_cases/test_work_order_service.py test_cases/test_work_order_repositories.py test_cases/test_api.py -q -rs
```

2026-10-22 实测 **103 passed、2 warnings**。其中 API 用假 Service 验证 HTTP 契约，Service 用假连接验证事务、清理与脱敏，Repository 验证 SQL 参数绑定；均不是 MySQL 实测结果。

## Day 20：HTTP 到真实 MySQL，以及 Swagger 演示

完成上面的本机配置后，在清除密码前运行：

```powershell
.\venv\Scripts\python.exe -m pytest test_cases/test_work_order_mysql.py test_cases/test_work_order_api_mysql.py --run-db -q -rs --tb=short
```

预期 **13 passed**，包含 6 条 Service 场景和 7 条 HTTP 场景。HTTP 测试通过真实 app、Pydantic、Service、Repository、MySQL，仅替换连接工厂以追踪清理，不是假数据库。TestClient 是进程内 HTTP 测试，不等于浏览器或真实 TCP/Uvicorn 验收。若执行全部数据库测试 `-m db --run-db`，加上 Day 12 的 4 条后预期 **17 passed**。任一失败先处理，不继续演示。

Swagger 演示使用两个 PowerShell 终端，都进入项目根目录、各自按前文配置 `EBIKE_DB_*`，并移除 `DASHSCOPE_API_KEY`。仅监听本机，不需要模型、硬件日志或向量库。

终端 A 启动 API：

```powershell
.\venv\Scripts\python.exe -m uvicorn ebike_ai.api:app --host 127.0.0.1 --port 8000
```

终端 B 准备独立演示数据并保持运行：

```powershell
.\venv\Scripts\python.exe -m scripts.work_order_demo --run-db
```

这是仓库内教学脚本，复用测试数据隔离与清理工具，不随生产包安装。它只允许练习库，打印随机编号、测试车辆 ID 和两份 JSON，不打印凭据。

在 [本机 Swagger](http://127.0.0.1:8000/docs) 完成：

1. 展开“维修工单”，将终端 B 的两份 JSON 分别原样提交到 `POST /work-orders`，预期 201，记下各自 ID。
2. 按 ID、按业务编号查询，两种结果应一致，车辆、电池、状态、未知时间字段与请求相符。
3. 重复提交第一份 JSON，预期 409、`DUPLICATE_WORK_ORDER`，再次查询原单内容不变。
4. 将第一份 JSON 的 vehicle_id 临时改为 0，预期 422；不要提交其他有效的新编号或修改已登记请求内容。
5. 回到终端 B 按 Enter。脚本核对并清理本次演示记录；查看对应 manifest 的 `state` 为 `cleaned`。再查询原工单，预期 404。
6. 停止终端 A 的 API，在两个终端清除 `EBIKE_DB_PASSWORD`。端口冲突时同时调整 API 启动端口和浏览器地址，不停止其他进程。

如果修改了已登记请求的有效内容，清理工具会因内容不匹配而停止，这是为了避免误删；保留 manifest 后人工核对，不重新运行脚本冒充上次清理完成。浏览器 `/docs` 需要加载 Swagger CDN，页面无法加载时先区分前端资源问题与 API 故障。

## Day 21：回归与学习验收

```powershell
Remove-Item Env:DASHSCOPE_API_KEY -ErrorAction SilentlyContinue
Remove-Item Env:PYTEST_ADDOPTS -ErrorAction SilentlyContinue
.\venv\Scripts\python.exe -m pip check
.\venv\Scripts\python.exe -m pytest -q -rs --junitxml=reports/week3/junit.xml
```

分别记录离线、真实 MySQL、Swagger 演示的实际结果。默认跳过真实服务测试，不能把跳过写成通过；报告和 manifest 均留在已忽略的 reports 中。

每天约 3 小时：20 分钟回顾、40 分钟学一个概念、80 分钟实现与走查、25 分钟验证、15 分钟记录及提交。今天已生成的代码可以分日阅读和复验，不要求一天消化整周内容。

独立回答以下问题，再对照代码验证，答案未收到前保持“待学习验收”：

- 为什么 Pydantic 校验合法仍不能证明电池属于该车？是哪一层负责归属？
- 为什么 Repository 不提交，而 Service 使用一个独占连接管理整项操作？
- 为什么同连接查到记录不代表已提交？新连接查询又不能证明哪些事情？
- 为什么同样是接口报错，commit 未知与重复编号要采用不同处理？
- 为什么关闭连接失败时仍可能返回 201？返回 201 为什么不代表维修完成？
- 哪些分支可以用假连接验证，哪些结论必须用真实 MySQL、HTTP 或并发实验验证？

本周未实现诊断隔离、完整幂等协议、连接池、并发锁实验或维修业务闭环；原 `/diagnose` 的全局 Agent 与异常透传风险仍待后续处理。工单接口不调用 Agent，也不把它的风险记为已经修复。

### 本轮验证记录（2026-10-22）

- 全量离线：`201 passed、19 skipped、2 warnings`，160.20 秒；JUnit：`reports/week3/junit.xml`。跳过 2 条真实模型和 17 条真实数据库测试。
- 收集分类：unit 110、integration 108（含 db 17）、evaluation 2（同时 live），共 220 条。`pip check` 通过。
- 临时启动真实 Uvicorn、清除子进程模型与数据库配置后，HTTP `/health`、`/docs` 返回 200；OpenAPI 包含工单路由，创建工单返回 503、DATABASE_NOT_CONFIGURED。验证后停止本次服务，没有连接 MySQL 或模型。
- 演示脚本 `--help` 可运行；离线测试验证未开启 `--run-db` 时不读取配置，以及中断/失败时的清理尝试和脱敏。
- 真实 MySQL、浏览器 Swagger 交互、并发锁行为与学习独立复述均未验收；远端 CI 本轮未核验。两条弃用警告未在本次升级依赖处理。
