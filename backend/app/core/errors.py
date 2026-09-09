"""知识库系统自定义异常类 — 覆盖 LLM 调用、文档操作等核心错误场景。"""


class KnowledgeBaseError(Exception):
    """知识库系统基础异常，所有自定义异常均继承自此类。"""


class LLMError(KnowledgeBaseError):
    """LLM 调用失败或 Embedding 不可用。"""


class DuplicateDocumentError(KnowledgeBaseError):
    """尝试创建已存在的文档时抛出。"""


class DocumentNotFoundError(KnowledgeBaseError):
    """指定的文档不存在。"""
