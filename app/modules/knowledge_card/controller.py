from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.modules.knowledge_card.schema import KnowledgeCardResponse
from app.modules.knowledge_card.service import KnowledgeCardService

knowledge_card_router = APIRouter()


@knowledge_card_router.get("/tasks/{task_id}/knowledge-cards", response_model=KnowledgeCardResponse, summary="获取知识卡片")
def get_knowledge_cards(task_id: str, session: Session = Depends(get_db)):
    """
    获取知识卡片
    :param task_id:
    :param session:
    """
    return KnowledgeCardService.get_by_task(task_id, session)


@knowledge_card_router.post("/tasks/{task_id}/knowledge-cards/regenerate", response_model=KnowledgeCardResponse, summary="重新生成知识卡片")
def regenerate_knowledge_cards(task_id: str, session: Session = Depends(get_db)):
    """
    重新生成知识卡片
    :param task_id:
    :param session:
    :return:
    """
    return KnowledgeCardService.regenerate_for_task(task_id, session)
