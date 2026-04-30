from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.modules.qa.schema import (
    ConversationCreate,
    ConversationMessagesResponse,
    ConversationResponse,
    ConversationTurnResponse,
    ConversationMessageCreate,
    QaRequest,
    QaResponse,
)
from app.modules.qa.service import QaService

qa_router = APIRouter()


@qa_router.post("/qa", response_model=QaResponse, summary="执行单轮问答")
def qa(req: QaRequest, session: Session = Depends(get_db)):
    """
    查询
    :param req:
    :param session:
    :return:
    """
    return QaService.qa(
        query=req.query,
        session=session,
        kb_id=req.kb_id,
        task_id=req.task_id,
        tone=req.tone,
        top_k=req.top_k
    )


@qa_router.post("/conversations", response_model=ConversationResponse, summary="创建会话")
def create_conversation(req: ConversationCreate, session: Session = Depends(get_db)):
    """
    创建会话
    :param req:
    :param session:
    :return:
    """
    return QaService.create_conversation(req, session)


@qa_router.get("/conversations", response_model=list[ConversationResponse], summary="获取会话列表")
def list_conversations(session: Session = Depends(get_db)):
    """
    列出会话
    :param session:
    :return:
    """
    return QaService.list_conversations(session)


@qa_router.get("/conversations/{conversation_id}/messages", response_model=ConversationMessagesResponse, summary="获取会话消息")
def get_conversation_messages(conversation_id: str, session: Session = Depends(get_db)):
    """
    获取会话消息
    :param conversation_id:
    :param session:
    :return:
    """
    return QaService.get_conversation_messages(conversation_id, session)


@qa_router.post("/conversations/{conversation_id}/messages", response_model=ConversationTurnResponse, summary="发送会话消息")
def create_conversation_message(
    conversation_id: str,
    req: ConversationMessageCreate,
    session: Session = Depends(get_db)
):
    """
    创建会话消息
    :param conversation_id:
    :param req:
    :param session:
    :return:
    """
    return QaService.create_conversation_turn(conversation_id, req, session)
