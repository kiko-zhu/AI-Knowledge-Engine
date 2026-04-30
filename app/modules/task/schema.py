from typing import Optional
from pydantic import BaseModel
from datetime import datetime

"""
给接口用
"""
class TaskCreate(BaseModel):
    """
    说明：TaskCreate 类，封装当前模块的数据结构或业务逻辑。
    """
    file_name: str                          # 文件名
    file_path: str                          # 文件路径
    knowledge_base_id: str                  # 知识库id

class TaskResponse(BaseModel):
    """
    说明：TaskResponse 类，封装当前模块的数据结构或业务逻辑。
    """
    id: str                                 # 任务id
    file_name: str                          # 文件名
    file_path: str                          # 文件路径
    status: str                             # 任务状态
    progress: int = 0                       # 任务进度，0-100
    chunk_count: int = 0                    # 当前任务对应切片数量
    result: Optional[str] = None            # 任务结果
    error_message: Optional[str] = None     # 错误信息
    created_at: datetime                    # 创建时间
    updated_at: datetime                    # 更新时间
    knowledge_base_id: str                  # 知识库id

    class Config:
        """
        说明：Config 类，封装当前模块的数据结构或业务逻辑。
        """
        from_attributes = True

class KnowledgeBaseCreate(BaseModel):
    """
    说明：KnowledgeBaseCreate 类，封装当前模块的数据结构或业务逻辑。
    """
    name: str                               # 知识库名称
    description: Optional[str] = None       # 描述


class KnowledgeBaseEnabledUpdate(BaseModel):
    """
    说明：KnowledgeBaseEnabledUpdate 类，封装当前模块的数据结构或业务逻辑。
    """
    enabled: bool                           # 是否启用检索


class KnowledgeBaseResponse(BaseModel):
    """
    说明：KnowledgeBaseResponse 类，封装当前模块的数据结构或业务逻辑。
    """
    id: str                                 # 知识库id
    name: str                               # 名称
    description: Optional[str]              # 描述
    enabled: bool = True                    # 是否启用检索
    created_at: datetime                    # 创建时间

    class Config:
        """
        说明：Config 类，封装当前模块的数据结构或业务逻辑。
        """
        from_attributes = True


class KnowledgeBaseStatsResponse(BaseModel):
    """
    说明：KnowledgeBaseStatsResponse 类，封装当前模块的数据结构或业务逻辑。
    """
    id: str                                 # 知识库 ID
    name: str                               # 知识库名称
    description: Optional[str] = None       # 知识库描述
    enabled: bool = True                    # 是否启用检索
    created_at: datetime                    # 创建时间
    document_count: int = 0                 # 知识库下文档数量
    chunk_count: int = 0                    # 知识库下 chunk 总数


class KnowledgeBaseChunkItemResponse(BaseModel):
    """
    说明：KnowledgeBaseChunkItemResponse 类，封装当前模块的数据结构或业务逻辑。
    """
    task_id: str                            # 文档任务 ID
    file_name: str                          # 来源文件名
    file_path: str                          # 来源文件路径
    chunk_index: int                        # chunk 索引
    section: Optional[str] = None           # chunk 所属章节
    content: str                            # chunk 内容
    length: int                             # chunk 文本长度
    created_at: datetime                    # chunk 创建时间


class KnowledgeBaseChunksResponse(BaseModel):
    """
    说明：KnowledgeBaseChunksResponse 类，封装当前模块的数据结构或业务逻辑。
    """
    kb_id: str                              # 知识库 ID
    kb_name: str                            # 知识库名称
    total: int                              # 总条数
    page: int                               # 当前页码
    page_size: int                          # 每页数量
    items: list[KnowledgeBaseChunkItemResponse]  # chunk 列表


class KnowledgeBaseDocumentItemResponse(BaseModel):
    """
    说明：KnowledgeBaseDocumentItemResponse 类，封装当前模块的数据结构或业务逻辑。
    """
    task_id: str                            # 文档任务 ID
    file_name: str                          # 文件名
    file_path: str                          # 文件路径
    status: str                             # 任务状态
    progress: int = 0                       # 任务进度
    chunk_count: int = 0                    # chunk 数量
    created_at: datetime                    # 创建时间
    updated_at: datetime                    # 更新时间


class KnowledgeBaseDocumentsResponse(BaseModel):
    """
    说明：KnowledgeBaseDocumentsResponse 类，封装当前模块的数据结构或业务逻辑。
    """
    kb_id: str                              # 知识库 ID
    kb_name: str                            # 知识库名称
    total: int                              # 总条数
    page: int                               # 当前页码
    page_size: int                          # 每页数量
    items: list[KnowledgeBaseDocumentItemResponse]  # 文档列表


class ManagedDocumentResponse(BaseModel):
    """
    说明：ManagedDocumentResponse 类，封装当前模块的数据结构或业务逻辑。
    """
    task_id: str                            # 文档任务 ID
    file_name: str                          # 文件名
    file_path: str                          # 文件路径
    knowledge_base_id: str                  # 所属知识库 ID
    status: str                             # 任务状态
    progress: int = 0                       # 任务进度
    chunk_count: int = 0                    # chunk 数量
    created_at: datetime                    # 创建时间
    updated_at: datetime                    # 更新时间


class ManagedDocumentsListResponse(BaseModel):
    """
    说明：ManagedDocumentsListResponse 类，封装当前模块的数据结构或业务逻辑。
    """
    total: int                              # 总条数
    page: int                               # 当前页码
    page_size: int                          # 每页数量
    items: list[ManagedDocumentResponse]    # 文档管理列表
