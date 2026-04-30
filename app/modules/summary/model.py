from sqlalchemy import Column, DateTime, ForeignKey, String, Text

from app.core.db import Base


class DocumentSummary(Base):
    """
    说明：DocumentSummary 类，封装当前模块的数据结构或业务逻辑。
    """
    __tablename__ = "document_summaries"

    id = Column(String, primary_key=True)                           # ID
    task_id = Column(String, ForeignKey("tasks.id"), unique=True)   # 任务ID
    file_name = Column(String)                                      # 文件名
    summary_text = Column(Text, nullable=True)                      # 摘要
    keywords_json = Column(Text, nullable=True)                     # 关键词
    sections_json = Column(Text, nullable=True)                     # 章节
    status = Column(String)                                         # 状态
    error_message = Column(Text, nullable=True)                     # 错误信息
    created_at = Column(DateTime)                                   # 创建时间
    updated_at = Column(DateTime)                                   # 更新时间
