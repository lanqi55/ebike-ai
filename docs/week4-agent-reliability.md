# 第四周：Agent 可靠性与请求隔离

本周工程目标是隔离请求上下文、约束失败行为、停止未经确认的案例写入。API 每次独立诊断；命令行一次运行内保留最近五轮成功交流。本周不提供 API 多轮会话、人工审核入库或完整维修工单闭环。

## Day 22：先复现，再修改生命周期

先用自己的话复习：同一数据库连接中的两项未提交修改，会被该连接的一次 commit 一起提交；rollback 不能撤销已经提交的数据，恢复需要新的受控操作。对比本周问题：两个请求共用一个有状态对象，也会读到此前留下的状态。

阅读 `api.py` 的 `diagnose()`、`agent_factory.py` 和 `AgentLoop.memory`。两个 HTTP 请求都成功不代表没有串话，必须查看实际传给模型的 messages。

```powershell
Remove-Item Env:DASHSCOPE_API_KEY -ErrorAction SilentlyContinue
Remove-Item Env:PYTEST_ADDOPTS -ErrorAction SilentlyContinue
.\venv\Scripts\python.exe -m pytest test_cases/test_agent_isolation.py -k "shared_agent or sequential" -q
```

旧实现的定向实验：复用同一 Agent 能观察到车辆甲出现在车辆乙的历史中；对 HTTP 请求要求新建两个 Agent 时，实际只创建一个，出现 `assert 1 == 2`。修改后两项测试通过。保留的“旧行为复现”测试说明命令行有意保留历史的行为，不代表 API 仍有缺陷。

独立解释：为什么给全局 Agent 加锁只能串行化调用，仍然不能隔离用户历史？

## Day 23：用确定性交错证明隔离

```powershell
.\venv\Scripts\python.exe -m pytest test_cases/test_agent_isolation.py -k concurrent -q
```

测试在两个假模型的第一次调用设置 Barrier，使两个请求都进入执行阶段后再继续，避免依赖 sleep 猜测调度。检查每个模型的全部输入、每次回答和工具参数；另一个场景让甲请求失败而乙成功。屏障与 future 都有等待上限，失败不会无限挂起。

这些是进程内 HTTP 与线程交错测试，不是吞吐压测，也不证明真实模型服务的并发容量。

## Day 24：统一组装，分开生命周期

API 与命令行均使用 `build_agent()`。它每次创建新 Agent、新工具注册中心和短期记忆；API 每请求调用一次，命令行进入循环前调用一次。默认只注册 `get_battery_data` 和 `search_repair_knowledge`，提示词从实际注册清单生成。

```powershell
.\venv\Scripts\python.exe -m pytest test_cases/test_agent_factory.py -q
```

传入假模型、假工具即可测试，不必为了测试准备 Key、硬件或向量库。导入入口不创建模型客户端或案例库。需要真实模型时才检查配置。检索时缺少已有 Chroma 数据文件直接报告 `KNOWLEDGE_NOT_READY`，不会用空库冒充已准备好的知识。

独立解释：为什么共用工厂函数不等于共用同一个对象？

## Day 25：工具契约与可解释的失败

有参数工具必须提供 Pydantic 参数模型；Schema 与实际校验来自同一来源。`SearchArguments` 要求非空且不超过 500 字的字符串，禁止额外字段和数字隐式转换；无参数工具也禁止多余参数。

模型收到的工具内容仍是 JSON 字符串，其内部结构统一为：

```json
{"ok": true, "data": "检索到的维修资料", "error": null}
```

```json
{"ok": false, "data": null, "error": {"code": "TOOL_ARGUMENTS_INVALID", "message": "工具参数不符合要求"}}
```

工具返回数据须可序列化；硬件结果复用现有电压一致性校验，知识检索结果须为文本。校验通过只代表数据契约满足，不代表电池安全。成功但无匹配资料是 `ok=true, data=""`，Agent 返回固定的证据不足与人工复检提示；执行失败则停止本次诊断，避免模型把失败信息猜成维修依据。

`tool_trace` 保留既有字段并增加 `error_code`；成功率读取明确的 `success`。工具调用 Judge 要求预期工具成功执行；幻觉 Judge 仅使用成功结果中的 `data`。`hardware_data`、`retrieved_docs` 仍为字符串，消费者解析后应读取新契约，不再假定其直接等于原始电压字典或文本。

```powershell
.\venv\Scripts\python.exe -m pytest test_cases/test_tool_contract.py test_cases/test_tool_registry.py -q
```

## Day 26：真正生效的超时与重试

当前默认：模型与 Embedding 单次网络超时均为 30 秒，最多尝试 2 次（包含首次），间隔 1 秒。配置使用 `max_attempts`，替代含义容易混淆的旧 `max_retries`。Agent 迭代上限仍为 10。

模型通过 DashScope 的 `request_timeout` 传到实际 HTTP 调用；Embedding 使用 `HTTPSConnection(..., timeout=...)`。通过真实 SDK、假 HTTP 传输验证参数和工具消息往返，不调用真实服务。传入已有 ChatTongyi 时复制其配置，将内部尝试次数设为 1，避免改变调用方对象及多层重试叠加。

仅超时、连接中断及 429/500/502/503/504 服务响应可重试；鉴权、参数错误、SSL 错误、无效响应不自动重试。每次 Embedding 尝试独立建连，成功失败均关闭。网络层超时不是整次诊断的严格墙钟期限，慢速持续传输、DNS、多个工具和多轮模型调用仍可能延长总耗时；没有新增后台线程来假装取消同步调用。

`POST /diagnose` 成功响应保留 `answer / iteration_count / hardware_data / retrieved_docs / tool_trace`，不增加 `session_id`。错误响应为 `{"detail":{"code":"...","message":"..."}}`：

| HTTP | 典型错误码 | 含义 |
|---|---|---|
| 422 | `INPUT_INVALID` | 空白、超长或非文本输入，不回显原始输入 |
| 502 | `MODEL_RESPONSE_INVALID`、`TOOL_ARGUMENTS_INVALID`、`TOOL_NOT_FOUND`、`TOOL_OUTPUT_INVALID` | 上游内容或工具协议不符合契约 |
| 503 | `MODEL_NOT_CONFIGURED`、`MODEL_UNAVAILABLE`、`KNOWLEDGE_NOT_READY` | 配置缺失或依赖不可用 |
| 503 | `TOOL_DATA_UNAVAILABLE`、`TOOL_EXECUTION_FAILED` | 缺少有效测量或工具执行失败 |
| 503 | `AGENT_ITERATION_LIMIT` | 达到迭代上限，诊断未完成；不是网络超时 |
| 504 | `MODEL_TIMEOUT`、`EMBEDDING_TIMEOUT`、`TOOL_TIMEOUT` | 网络或工具报告超时 |
| 500 | `INTERNAL_ERROR` | 未预期的内部错误 |

完整错误定义见 `core/failures.py`。API、CLI 和工具边界不透传原始异常。应用日志只记录受控错误码；DashScope 的调试记录替换为固定提示，代价是不能直接依靠原始 SDK 调试文本排查。需要排查时使用错误码、工具轨迹和离线复现，不能开启原始请求头输出。

失败 Agent 通过 `DiagnosisError.state` 留下失败状态、轮数和轨迹，不存入成功短期历史。批量评测保留失败运行，新增 `failure_count / failure_codes`；失败轮次各质量项计失败，不再调用评委模型，避免把失败当正常答案或从分母中丢弃。最后一轮正常回答不再被最大迭代指标误判为耗尽。

```powershell
.\venv\Scripts\python.exe -m pytest test_cases/test_agent_reliability.py test_cases/test_embedding_reliability.py test_cases/test_evaluation_failures.py -q
```

## Day 27：停止未经确认的长期写入

诊断入口不初始化长期案例库、不调用 `add_case()`、不注册历史案例工具。命令行成功与失败场景均有禁止写库测试。旧库保留，不能自动认定可信，也不做删除或迁移。

本周没有人工审核流程或“已确认案例”写入接口，因此只完成停止污染。维修师确认、审核证据、可信案例整理与查询恢复，需要后续独立业务目标。

独立解释：为什么 AI 回答成功、HTTP 200 和维修师确认是三个不同事实？

## Day 28：演示、回归与学习复述

本仓库当前环境为 `venv`；按 README 新建环境使用 `.venv` 时替换解释器路径。

```powershell
Remove-Item Env:DASHSCOPE_API_KEY -ErrorAction SilentlyContinue
Remove-Item Env:PYTEST_ADDOPTS -ErrorAction SilentlyContinue
.\venv\Scripts\python.exe -m scripts.week4_agent_demo
.\venv\Scripts\python.exe -m pip check
.\venv\Scripts\python.exe -m pytest -q -rs --junitxml=reports/week4/junit.xml
```

演示先显示共用对象的旧行为，再通过真实路由和 Agent 展示顺序隔离、两个并发成功、一个失败而另一个成功。只使用假依赖，并额外阻断外部连接；允许 Windows 事件循环必需的本机 socketpair 通信，不启动 HTTP 监听端口，不准备数据库，不保存案例。实际结果应以命令退出码与断言为准。

每天仍按 20 分钟复习、40 分钟概念、80 分钟实现走查、25 分钟验证、15 分钟记录推进。代码已实现不代表一天掌握全周内容。以下问题必须由用户独立回答，未回答前保持待验收：

1. 锁与请求独占对象分别解决什么问题？请求级方案为什么不能自动支持 API 连续追问？
2. 怎样证明并发用例确实发生了交错，而不只是连续执行？
3. 工具 Schema 为什么不能替代运行时参数校验？空检索结果为什么不是工具异常？
4. 哪些错误应重试？“最多尝试两次”与“重试两次”有什么区别？
5. 为什么 30 秒网络超时和 10 轮迭代上限都不等于整个接口 30 秒内结束？
6. 为什么错误诊断不该进入长期案例？当前哪些人工审核工作仍未完成？

本周未验证真实诊断质量、真实服务容量或付费评委链路；`/evaluate` 仍是同步接口，其鉴权、成本限制和任务化不在本周范围。旧 Key 是否轮换仍需用户确认，不因本次错误边界修复就认为旧凭据已安全。真实调用只在另行明确开启并准备凭据、网络、测量和知识库后进行。

## 本轮工程证据（2026-10-23）

- 全量离线回归：285 passed、19 skipped、2 warnings，109.89 秒；报告为已忽略的 `reports/week4/junit.xml`。跳过 2 条真实模型及 17 条 MySQL 测试，不能算作真实服务通过。
- 共收集 304 条：unit 156、integration 146（含 db 17）、evaluation 2（同时 live）。每条测试恰有一个主要分类；第四周比此前新增 84 条离线检查。
- `pip check` 通过。离线演示退出码 0，顺序和并发均通过断言，其中部分失败场景返回 503/200。
- 可靠性代码提交 `d78ee18` 的 [GitHub Actions](https://github.com/lanqi55/ebike-ai/actions/runs/39925008228) 已完成且成功；该记录只证明工作流所选离线检查通过。
- 未新增生产依赖、未修改数据库结构；原有评测脚本修改保留。工程验收完成不等于用户学习验收，六道复述题仍待用户回答。
