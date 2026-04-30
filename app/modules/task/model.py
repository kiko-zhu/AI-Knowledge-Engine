from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text

from app.core.db import Base

class Task(Base):
    """
    说明：Task 类，封装当前模块的数据结构或业务逻辑。
    """
    __tablename__ = "tasks"

    id = Column(String, primary_key=True)           # 任务id
    file_name = Column(String)                      # 文件名
    file_path = Column(String)                      # 文件路径
    status = Column(String)                         # 任务状态
    progress = Column(Integer, default=0)           # 任务进度，0-100
    result = Column(String, nullable=True)          # 任务结果
    error_message = Column(String, nullable=True)   # 错误信息
    created_at = Column(DateTime)                   # 创建时间
    updated_at = Column(DateTime)                   # 更新时间
    knowledge_base_id = Column(String, ForeignKey("knowledge_bases.id"))    # 知识库id


class KnowledgeBase(Base):
    """
    说明：KnowledgeBase 类，封装当前模块的数据结构或业务逻辑。
    """
    __tablename__ = "knowledge_bases"

    id = Column(String, primary_key=True)           # 知识库id
    name = Column(String, unique=True)              # 名称
    description = Column(String, nullable=True)     # 描述
    enabled = Column(Boolean, default=True)         # 是否启用检索
    created_at = Column(DateTime)                   # 创建时间



class DocumentChunk(Base):
    """
    说明：DocumentChunk 类，封装当前模块的数据结构或业务逻辑。
    """
    __tablename__ = "document_chunks"

    id = Column(String, primary_key=True)           # 文档块id
    task_id = Column(String)                        # 任务id
    content = Column(Text)                          # 内容
    embedding = Column(Text)                        # 嵌入向量  存 json 字符串
    chunk_index = Column(Integer)                   # 块索引
    created_at = Column(DateTime)                   # 创建时间
