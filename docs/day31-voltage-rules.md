# 第 31 天：数据校验与确定性规则

`validate_battery_data()` 检查三串电压是否为有限、非负数字，以及总电压是否按两位小数等于分电压之和。这是数据契约，不能判断真实电池是否正常。

`evaluate_voltage_rules(measurement, context=..., rules=...)` 是不调用模型、不访问硬件的纯函数。上下文包含 `battery_type`、`series_count`、`measurement_condition`；规则必须包含来源、版本、明确区间及 `confirmed=True`。

| 结果 | 含义 |
|---|---|
| `invalid_data` | 数据不满足当前三串契约 |
| `insufficient_evidence` | 无测量、上下文不全，或没有已确认且适用的阈值 |
| `not_applicable` | 当前数据结构不能表达所声明的电池串数 |
| `conflict` | 同一适用条件有不同规则区间，需要人工核对 |
| `matched` | 至少一个电芯超出所选规则区间，仍不能直接归因或指定换件 |
| `passed` | 所测电压满足所选区间，不代表电池安全或整车正常 |

硬件工具仍返回原来的电压字段，另附 `rule_result`。该结果由服务端重新计算，不能信任日志自带的“正常”标签。因为当前日志尚无可信车辆关联，也没有父亲确认的业务阈值，生产路径默认不激活业务规则，明确列出缺失上下文。

现有三条案例均无电压测量，不能为其填入模拟器数据。当前规则测试的 2.0–4.0V **纯为算法合成区间，不是维修标准**；真实阈值以后须先取得适用电池的可靠资料和维修师确认，再新增来源记录及回归测试。

离线实验：

```powershell
.\venv\Scripts\python.exe -m pytest test_cases/test_voltage_rules.py test_cases/test_battery_data.py test_cases/test_tool_contract.py -q
```

学习验收：解释结构校验、规则适用条件、规则命中及维修师判断的区别；修改合成值，观察等于上下限和刚越界的结果；解释为何冲突规则不能静默选一个。
