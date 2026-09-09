"""知识库检索评测包。

提供评测数据自动生成、数据加载/保存、指标计算和评测执行的完整工具链。

核心模块：
- dataset: EvalItem 数据模型和数据集加载/保存
- gen_dataset: LLM 驱动评测数据自动生成（入库调用）
- storage: 分文档数据存储和 JSONL 评测历史追加
- metrics: 标准 Recall@K 和 MRR 指标计算
- run_eval: 评测入口脚本（无参数，一键运行）
- merge_to_global: 手动合并分文档数据到全局数据集
"""
