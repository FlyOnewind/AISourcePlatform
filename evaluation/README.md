# 知识库检索评测

文档入库后 LLM 自动生成评测数据 → 人工确认合并 → 一键跑评测 → 结果追加到历史文件。

## 核心流程

```
入库自动生成 → datasets/unmerged/doc_{id}_{date}.json
                      │
          merge_to_global.py [--all | <doc_id>] (手动合并)
                      │        去重键: (doc_id, query)
                      │        auto 标注直接覆盖，manual 永远保护
                      │        合并后源文件 → datasets/merged/
                      ▼
               eval_dataset.json (全局数据集)
                      │
              run_eval.py [--no-rewrite] [--no-rerank] [--top-k N]
                      │        直接复用现有检索索引，不重建
                      │        过滤过期 chunk_id，剔除而非丢弃整条
                      ▼
          results/history.jsonl (JSONL 追加)
```

## 快速开始

### 1. 入库文档 → 自动生成评测数据

文档入库成功后，系统后台异步调用 LLM 生成评测数据，存入 `datasets/unmerged/` 目录（未合并）。超过 80 个知识块的大文档自动分片生成，每片独立生成 `AUTO_EVAL_QUERIES_PER_DOC` 条查询，总量上限为 `AUTO_EVAL_QUERIES_PER_DOC * 2`。

LLM 生成的查询涵盖多种真实检索风格：完整疑问句、关键词组合、口语片段、祈使/陈述句。

```env
# 是否启用入库自动生成（默认 true）
AUTO_EVAL_ENABLED=true
# 每个文档生成的查询数量（默认 3）
AUTO_EVAL_QUERIES_PER_DOC=3
```

**注意**：同一文档重入库后，旧数据集文件会被自动删除，避免过期标注混入评测。

### 2. 手动生成评测数据

除了入库自动生成外，也可对已有文档手动生成评测数据：

```bash
# 交互模式
python evaluation/manual_gen_dataset.py

# 指定文档
python evaluation/manual_gen_dataset.py --doc <doc_id>

# 指定分类（跨文档）
python evaluation/manual_gen_dataset.py --category <分类名>

# 全部活跃文档
python evaluation/manual_gen_dataset.py --all

# 列出文档和分类概览
python evaluation/manual_gen_dataset.py --list
```

### 3. 审核合并到全局数据集

确认 `datasets/unmerged/doc_{id}_{date}.json` 中的查询质量后，手动合并到全局数据集：

```bash
# 合并单个文档
python evaluation/merge_to_global.py <doc_id>

# 合并全部未合并文档
python evaluation/merge_to_global.py --all
```

- 去重键为 `(doc_id, query)`，不同文档的同名 query 不会互相覆盖
- `"source": "manual"` 的条目永远不会被覆盖
- `"source": "auto"` 的条目直接覆盖更新，过期的 chunk_id 由评测脚本过滤
- 合并完成后源文件自动移动到 `datasets/merged/`（已合并）

### 4. 运行评测

```bash
# 默认参数：rewrite=true, rerank=true, top_k=5
python evaluation/run_eval.py

# 自定义参数
python evaluation/run_eval.py --no-rewrite --no-rerank --top-k 10
```

评测步骤：
1. 加载全局数据集
2. **过滤过期标注** — 通过 `chunk_store.get_batch()` 查询预期 chunk 是否仍存在：全部失效的条目丢弃，部分失效的剔除过期 chunk_id
3. 直接复用现有检索索引（不重建）
4. **并发检索** — 8 路 `ThreadPoolExecutor` 并发调用检索管线
5. 按序计算四个指标：Hit@K、Recall@K、Precision@K、MRR

### 5. 查看评测历史

```bash
cat evaluation/results/history.jsonl | jq .
```

---

## 目录结构

```
evaluation/
├── __init__.py             # 包说明
├── dataset.py              # EvalItem 数据模型 + load_dataset() + save_dataset()
├── gen_dataset.py          # LLM 自动生成评测数据（入库时调用）
├── manual_gen_dataset.py   # 手动生成评测数据（对已有文档，支持交互/指定/全量模式）
├── storage.py              # 分文档存储（写入前删旧文件）+ JSONL 结果追加
├── metrics.py              # Hit@K + Recall@K + Precision@K + MRR + safe_mean
├── run_eval.py             # 评测入口脚本（支持 --no-rewrite/--no-rerank/--top-k）
├── merge_to_global.py      # 手动合并分文档数据到全局数据集
├── README.md
├── eval_dataset.json        # 全局评测数据集（人工标注 + 合并后的自动生成）
├── datasets/                # 运行时生成，不入库
│   ├── unmerged/            #   未合并 — 入库自动生成，待人工确认
│   │   └── doc_{id}_{date}.json
│   └── merged/              #   已合并 — merge_to_global.py 执行后移入
│       └── doc_{id}_{date}.json
└── results/                  # 运行时生成，不入库
    └── history.jsonl         #   评测历史（JSONL 每行一条记录）
```

---

## 评测指标

| 指标 | 说明 |
|------|------|
| **Hit@K** | top-K 至少命中一个期望 chunk 的查询比例（0/1 均值，K 可配置，默认 5） |
| **Recall@K** | 每条查询 top-K 命中数 / 期望总数，取所有查询的平均值 |
| **Precision@K** | 每条查询 top-K 命中数 / K，取所有查询的平均值 |
| **MRR** | 首个命中 chunk 排名倒数的均值（第1→1.0, 第3→0.333, 未命中→0） |

## JSONL 历史记录格式

`results/history.jsonl` 每行一条记录：

```json
{
  "timestamp": "2026-06-27T10:30:00",
  "search_params": {
    "rewrite": true,
    "rerank": true,
    "top_k": 5,
    "vector_top_k": 30,
    "bm25_top_k": 30,
    "rrf_top_k": 15
  },
  "metrics": {
    "hit_at_5": 0.870,
    "recall_at_5": 0.667,
    "precision_at_5": 0.420,
    "mrr": 0.583
  },
  "query_count": 100,
  "success_count": 99,
  "failure_count": 1
}
```

## 数据集格式

### 分文档数据集 (datasets/unmerged/doc_{id}_{date}.json)

```json
{
  "metadata": {
    "doc_id": "doc_abc123456789",
    "doc_title": "Python入门指南",
    "doc_version": 1,
    "generated_at": "2026-06-27T10:30:00",
    "generated_by": "auto-ingest",
    "chunk_count": 5,
    "query_count": 3
  },
  "items": [
    {
      "query": "Python是什么类型的编程语言？",
      "expected_chunk_ids": ["chunk_a1b2c3d4e5f6"],
      "expected_content_contains": ["解释型", "面向对象", "Guido van Rossum"],
      "doc_id": "doc_abc123456789",
      "doc_version": 1,
      "source": "auto"
    }
  ]
}
```

### 全局数据集 (eval_dataset.json)

扁平数组，每个分文档的 items 直接合并：

```json
[
  {
    "query": "Python是什么类型的编程语言？",
    "expected_chunk_ids": ["chunk_a1b2c3d4e5f6"],
    "expected_content_contains": ["解释型", "面向对象"],
    "doc_id": "doc_abc123456789",
    "doc_version": 1,
    "source": "auto"
  }
]
```

## 人工标注

直接编辑 `eval_dataset.json`，设置 `"source": "manual"`：

```json
[
  {
    "query": "你的查询问题",
    "expected_chunk_ids": ["chunk_id1"],
    "expected_content_contains": ["关键词1"],
    "doc_id": "doc_abc123",
    "doc_version": 1,
    "source": "manual"
  }
]
```

`"source": "manual"` 是关键 — 合并时人工标注条目永远不会被自动生成数据覆盖。

## 配置

```env
# 入库后自动生成评测数据（默认 true）
AUTO_EVAL_ENABLED=true
# 每个文档生成的查询数量（默认 3）
AUTO_EVAL_QUERIES_PER_DOC=3
```

## 生命周期

```
文档初次入库 → datasets/unmerged/doc_{id}_v1.json 生成
文档重入库   → 旧文件自动删除 → datasets/unmerged/doc_{id}_v2.json 生成（doc_version=2）
merge_to_global → 按 (doc_id, query) 去重，auto 覆盖、manual 保护 → 源文件 → merged/
run_eval    → 过滤过期 chunk_id → 复用现有索引 → 评测 → history.jsonl
```
