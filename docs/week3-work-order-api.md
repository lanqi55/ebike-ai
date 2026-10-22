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
