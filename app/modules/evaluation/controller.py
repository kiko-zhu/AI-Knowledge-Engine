from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.modules.evaluation.schema import EvaluationMetricsResponse, FeedbackCreate, FeedbackResponse
from app.modules.evaluation.service import EvaluationService

evaluation_router = APIRouter()


@evaluation_router.post("/messages/{message_id}/feedback", response_model=FeedbackResponse, summary="提交回答反馈")
def create_feedback(message_id: str, req: FeedbackCreate, session: Session = Depends(get_db)):
    """
    提交回答反馈
    :param message_id:
    :param req:
    :param session:
    :return:
    """
    return EvaluationService.create_feedback(message_id, req, session)


@evaluation_router.get("/evaluation/metrics", response_model=EvaluationMetricsResponse, summary="获取评估指标")
def get_metrics(session: Session = Depends(get_db)):
    """
    获取评估指标
    :param session:
    :return:
    """
    return EvaluationService.get_metrics(session)
