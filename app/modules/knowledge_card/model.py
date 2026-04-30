from sqlalchemy import Column, DateTime, ForeignKey, String, Text

from app.core.db import Base


class KnowledgeCardSet(Base):
    """
    知识卡片集合
    """
    __tablename__ = "knowledge_card_sets"

    id = Column(String, primary_key=True)                           # ID
    task_id = Column(String, ForeignKey("tasks.id"), unique=True)   # 任务ID
    file_name = Column(String)                                      # 文件名
    cards_json = Column(Text, nullable=True)                        # 卡片JSON
    status = Column(String)                                         # 状态
    error_message = Column(Text, nullable=True)                     # 错误信息
    created_at = Column(DateTime)                                   # 创建时间
    updated_at = Column(DateTime)                                   # 更新时间
