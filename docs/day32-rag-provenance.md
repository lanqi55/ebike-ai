# 第 32 天：RAG 来源与版本

知识工具的外层仍是 `ok/data/error`；`data` 改为片段列表，空列表表示检索成功但无结果。每片包含 `doc_id`、`version`、`chunk_id`、`source`、`content`、`confirmation`、`source_kind`、`provenance_status`。

- 文档编号用于区分原件，版本是内容的 SHA256 指纹，不冒充出版日期或维修日期。
- 片段编号包含文档编号、版本前缀和切分序号。同一语料重复构建不重复添加片段；修改一个案例会生成该案例的新版本。
- 既有 Word/PDF 默认标记 `unconfirmed`，不因能解析就视为维修师确认；案例只导入 `confirmed` 的记录。
- 旧向量库没有元数据时，版本、片段编号等保留 `null`，标记 `missing`；不能补造来源或作为已确认引用。

建库改为按语料指纹写独立集合，核对实际写入的正文、编号和元数据后，再原子更新向量库目录下的 `evidence_manifest.json`。检索只使用清单指定集合；构建失败不切换入口，旧集合保留。累计旧集合会占用磁盘，本周不自动删除；后续清理前应确认不再被引用。

已有项目库不会因安装或运行离线测试自动迁移。显式运行下面命令才构建新的真实 Embedding 快照，需要 Key、网络并会产生费用：

```powershell
.\venv\Scripts\python.exe -m ebike_ai.build_rag
```

本周默认使用假 Embedding 和临时库验证，不执行上述付费命令。`/diagnose` 的 `retrieved_docs` 字段仍为 JSON 字符串，其内层 `data` 为列表；外部消费者必须适配，不可继续按纯正文处理。

离线实验：

```powershell
.\venv\Scripts\python.exe -m pytest test_cases/test_knowledge_provenance.py test_cases/test_embedding_reliability.py test_cases/test_tool_contract.py -q
```

学习验收：分别解释文档编号、版本、片段编号的作用；指出“片段可追溯”与“诊断正确”的区别；说明为什么失败时不能先改当前知识库入口。
