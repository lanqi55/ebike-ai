# 第 12 天：Python 数据库读写与事务边界

目标：在已有 `ebike_ai_day11.vehicle` 表中新增车辆、按 ID 查询，再回滚验证。今天不建表、不接 API，不把这个小实验称为维修业务闭环。

## 1. 先判断，再执行

先独立回答，之后对照实验解释；回答经过提示后完成，应如实记录。

1. 容量为 NULL、0、空字符串分别表达什么？未知容量应该用哪个？
2. 在已经建好的表里插入车辆，同一事务查询成功，随后 ROLLBACK；记录和表分别会怎样？
3. 两次 INSERT 属于同一个业务操作，如果第一个 Repository 方法直接 COMMIT，第二次失败后还能一起撤销吗？
4. 含单引号的车辆备注应如何传给 SQL？测试使用虚构文本，不采集个人信息。

复习资料：[第 11 天约束实验](day11-mysql-lab.md)。CHECK 的 NULL/UNKNOWN、自增间隔和 DDL 隐式提交继续作为复习项，不因代码完成就标为掌握。

## 2. 代码与职责

```text
调用方读取配置 → 创建连接 → VehicleRepository(connection)
                             ├─ create(...) → 新 ID
                             └─ get_by_id(id) → 字典或 None
调用方决定 COMMIT / ROLLBACK，最后关闭连接
```

- [database.py](../src/ebike_ai/database.py)：`DatabaseConfig.from_env()` 在调用时读取配置；`connect_database()` 返回新的连接。导入模块不会读取数据库或创建连接。
- [vehicle.py](../src/ebike_ai/repositories/vehicle.py)：只负责两条参数化 SQL，不提交、不回滚、不关闭调用方的连接。约束异常保留给调用方判断。
- 连接使用 `utf8mb4`、UTC 会话、Day 11 严格模式；显式 `autocommit=False`；连接、读取、写入超时均为 5 秒。DATETIME 本身不会携带时区。
- 配置的密码字段不出现在 dataclass 的 repr 中。连接失败只提供固定提示与可用的 MySQL 错误号，不透传底层消息。不要主动打印环境变量、连接对象或启用包含敏感局部变量的调试输出。

新增直接依赖 `PyMySQL[rsa]==1.2.3`：驱动执行原生 SQL；`rsa` extra 带来 `cryptography` 等认证依赖，支持相关 MySQL 认证方式。替代方案是 MySQL Connector/Python，或驱动配合 SQLAlchemy；今天选择一个驱动以便专注 SQL 与事务，未引入 ORM、连接池或迁移工具。维护成本是驱动、认证依赖和服务端兼容性验证；精确版本仍不等同于完整传递依赖锁文件。

参考：[PyMySQL 安装与认证依赖](https://pypi.org/project/PyMySQL/)、[参数绑定及提交示例](https://pymysql.readthedocs.io/en/latest/user/examples.html)、[连接选项](https://pymysql.readthedocs.io/en/latest/modules/connections.html)。

## 3. 先运行离线检查

下面使用本项目现有 `venv`；若你按 README 创建的是 `.venv`，只修改第一行的解释器路径。

```powershell
$day12Python = ".\venv\Scripts\python.exe"
& $day12Python -m pip install -e ".[dev]" --index-url https://pypi.org/simple
& $day12Python -m pip check
Remove-Item Env:DASHSCOPE_API_KEY -ErrorAction SilentlyContinue
Remove-Item Env:PYTEST_ADDOPTS -ErrorAction SilentlyContinue
& $day12Python -m pytest test_cases/test_database.py -q
& $day12Python -m pytest -q -rs
```

逐条执行；任一命令失败先停止处理。默认 pytest 不需要 MySQL 或模型 Key。假连接测试能验证参数传递、配置、错误脱敏和事务职责，不能证明 MySQL 接受了 SQL 或执行了约束。

## 4. 在本机显式运行真实 MySQL 测试

前提：第 11 天已建好的练习库还在，MySQL 正在运行，你拥有该库的读写权限。无需重跑建表脚本。测试只允许 `ebike_ai_day11`，开始写入前读取 `information_schema` 核对车辆表的字段、InnoDB 引擎、排序规则与约束；结构不匹配则失败，不自动修复或清库。账号需能查看该库的元数据并对 vehicle 执行 SELECT/INSERT；测试不需要 DELETE 或 DDL 权限。

在你自己的 PowerShell 中设置配置。密码交互输入，不发到聊天、不写入源码或命令字面量。环境变量仅对该终端及其子进程生效，不能假定另一个已启动的 Codex 进程能读取到它；代码也不自动加载 `.env`。

```powershell
$day12Python = ".\venv\Scripts\python.exe"
$env:EBIKE_DB_HOST = "127.0.0.1"
$env:EBIKE_DB_PORT = "3306"
$env:EBIKE_DB_NAME = "ebike_ai_day11"
$env:EBIKE_DB_USER = Read-Host "输入本机 MySQL 用户名"
$day12Secret = Read-Host "输入本机 MySQL 密码" -AsSecureString
$env:EBIKE_DB_PASSWORD = [System.Net.NetworkCredential]::new("", $day12Secret).Password
Remove-Variable day12Secret
try {
    & $day12Python -m pytest test_cases/test_vehicle_mysql.py -m db --run-db -q -rs
    if ($LASTEXITCODE -ne 0) { throw "数据库测试未通过；请核对错误分类，不要发送密码或完整调试局部变量。" }
} finally {
    Remove-Item Env:EBIKE_DB_PASSWORD -ErrorAction SilentlyContinue
}
```

预期是 **4 passed**。如果只有 skipped，就没有运行真实测试；如果配置缺失、库名错误、连接失败或结构不匹配，会报错，不能视为通过。不需要开启 `--run-live`。

| 场景 | 断言与边界 |
|---|---|
| 新增后查询 | ID、业务编号、含引号的文本、中文备注一致；未知 model 保留为 None/SQL NULL |
| 查不到记录 | 无法存在的负数 UNSIGNED ID 返回 None |
| 重复编号 | 捕获 1062，并核对 uq_vehicle_code 唯一约束 |
| 显式回滚 | 原连接先查得到，ROLLBACK 后，新连接查不到该 ID |

每个测试使用 `D12` 开头的随机业务编号，fixture 在成功或失败后都尝试回滚并关闭全部连接。没有 COMMIT、DDL、DELETE、TRUNCATE，不删除既有数据。自增 ID 可能增长并留下间隔，这是本实验的已知副作用；不重置自增序号。

`--run-db` 只授权执行，不代替 `-m db` 筛选。即使有数据库环境变量，仅选择 marker、直接指定文件或开启 `--run-live` 也不会启用数据库测试。fixture 自身有第二道开关检查；CI 使用 `not live and not db`。

## 5. 解释结果与收尾

同一事务读到自己刚插入的记录，只能说明 SQL 已执行，不能说明已提交并持久保存。生产调用方通常在整项业务成功时 COMMIT、失败时 ROLLBACK、最后关闭连接；今天的真实测试只验证回滚，不验证提交后的持久化，也没有实现跨车辆电池归属等 Service 规则。

当天结束前独立解释：为什么 SQL 参数分开传？为什么 Repository 不自行提交？为什么需要新连接验证回滚？假连接与真实数据库各能证明什么？

分别记录：离线命令与结果、真实 MySQL 命令与结果、独立回答与提示后回答。代码实现完成不能替代真实数据库验收或学习验收。

## 6. 2026-10-18 验证记录

- 当前 Windows / Python 3.10 的既有 `venv` 中安装成功；PyMySQL 1.2.3 已进入项目安装元数据，`pip check` 通过。原镜像 TLS 失败后使用官方 PyPI 完成安装；未关闭证书验证，不称为全新环境验证。
- `python -m pytest test_cases/test_database.py -q`：16 passed，1 条既有弃用警告。
- 清除当前测试进程的模型 Key 与 PYTEST_ADDOPTS 后，`python -m pytest -q -rs --junitxml=reports/day12/junit.xml`：88 passed、6 skipped、2 条既有弃用警告，106.06 秒。
- 其中 2 条真实模型与 4 条真实数据库用例按开关跳过。数据库 fixture 成功/失败后的清理、配置拒绝、两个开关互不替代、CI 排除规则均使用离线替身验证。
- 用户随后在本机执行第 4 节测试并反馈终端摘要：`4 passed, 1 warning in 0.64s`。据此记录四条真实 MySQL 用例通过，覆盖表结构预检、车辆新增/查询、引号文本与 NULL、重复编号约束及回滚后新连接查询；这是用户本机执行反馈，Agent 未独立连接复跑，也未取得完整机器报告。
- 唯一警告来自 `conftest.py` 导入 `langchain-community` 的弃用提示，不是数据库测试失败。此次结果不证明提交后持久化、并发、完整业务流程或真实模型链路；依赖迁移另立小目标。
- 复习题和当天独立复述尚未收到回答，不标记学习验收通过。
