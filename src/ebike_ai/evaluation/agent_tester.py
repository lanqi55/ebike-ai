
class AgentTester:
    """通用 Agent 测试器：接收"建 agent 的函数" + Judge 列表，跑用例出报告"""

    def __init__(self, agent_factory, judges, metrics = None , runs=3):
        self.agent_factory = agent_factory   # 函数：case → agent（每次调用新建一个）
        self.judges = judges                 # Judge 列表（可插拔）
        self.metrics = metrics or []         # ← 性能指标函数列表
        self.runs = runs                     # 每个用例跑几次

    def test(self, cases):
        """跑测试：每个用例跑 runs 次，返回各维度通过率"""
        results = []
        for case in cases:
            passes_by_dim = {judge.name: [] for judge in self.judges}
            metric_values = {m.__name__ : [] for m in self.metrics}

            for _ in range(self.runs):
                agent = self.agent_factory(case)      # ← 关键：每次 new 一个（fresh memory）
                answer, state = agent.run(case["fault_text"])
                for judge in self.judges:
                    r = judge.judge(case, answer, state)
                    passes_by_dim[judge.name].append(r["passed"])

                for metric in self.metrics:
                    metric_values[metric.__name__].append(metric(state))

            row = {"fault_text": case["fault_text"], "category": case["category"]}
            for name, passes in passes_by_dim.items():
                valid = [p for p in passes if p is not None]
                row[name] = sum(valid) / len(valid) if valid else None

            for name, values in metric_values.items():
                valid = [v for v in values if v is not None]
                row[name] = sum(valid) / len(valid) if valid else None

            results.append(row)

        return results
