from sqlalchemy import Column, DateTime, ForeignKey, String, Text

from app.core.db import Base


class QaLog(Base):
    """
    问答日志
    """
    __tablename__ = "qa_logs"

    id = Column(String, primary_key=True)                                                           # id
    conversation_id = Column(String, ForeignKey("conversations.id"), nullable=True)                 # 对话_id
    user_message_id = Column(String, ForeignKey("conversation_messages.id"), nullable=True)         # 用户_消息_id
    assistant_message_id = Column(String, ForeignKey("conversation_messages.id"), nullable=True)    # 助手_消息_id
    kb_id = Column(String, nullable=True)                                                           # 知识库_id
    query = Column(Text)                                                                            # 查询
    rewritten_query = Column(Text, nullable=True)                                                   # 重写查询
    answer = Column(Text)                                                                           # 答案
    answer_type = Column(String, nullable=True)                                                     # 答案类型
    sources_json = Column(Text, nullable=True)                                                      # 来源
    created_at = Column(DateTime)                                                                   # 创建时间


class MessageFeedback(Base):
    """
    消息反馈
    """
    __tablename__ = "message_feedback"                                                              # 表名

    id = Column(String, primary_key=True)                                                           # id
    message_id = Column(String, ForeignKey("conversation_messages.id"))                             # 消息_id
    conversation_id = Column(String, ForeignKey("conversations.id"), nullable=True)                 # 对话_id
    rating = Column(String)                   # helpful / unhelpful                                 # 评价
    comment = Column(Text, nullable=True)                                                           # 评论
    created_at = Column(DateTime)                                                                   # 创建时间
