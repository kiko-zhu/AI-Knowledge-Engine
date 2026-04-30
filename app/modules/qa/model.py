from sqlalchemy import Column, DateTime, ForeignKey, String, Text

from app.core.db import Base


class Conversation(Base):
    """
    说明：Conversation 类，封装当前模块的数据结构或业务逻辑。
    """
    __tablename__ = "conversations"

    id = Column(String, primary_key=True)                                       # UUID
    title = Column(String, nullable=True)                                       # 会话标题
    kb_id = Column(String, ForeignKey("knowledge_bases.id"), nullable=True)     # 知识库 ID
    tone = Column(String, nullable=True)                                        # 语气
    created_at = Column(DateTime)                                               # 创建时间
    updated_at = Column(DateTime)                                               # 更新时间


class ConversationMessage(Base):
    """
    说明：ConversationMessage 类，封装当前模块的数据结构或业务逻辑。
    """
    __tablename__ = "conversation_messages"

    id = Column(String, primary_key=True)                                       # UUID
    conversation_id = Column(String, ForeignKey("conversations.id"))            # 会话 ID
    role = Column(String)              # user / assistant                       # 角色
    content = Column(Text)                                                      # 内容
    answer_type = Column(String, nullable=True)                                 # 答案类型
    answer_payload = Column(Text, nullable=True)   # JSON string                # 答案内容
    sources = Column(Text, nullable=True)   # JSON string                       # 来源
    created_at = Column(DateTime)                                               # 创建时间
