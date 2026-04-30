from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.modules.summary.schema import SummaryResponse
from app.modules.summary.service import SummaryService

summary_router = APIRouter()


@summary_router.get("/tasks/{task_id}/summary", response_model=SummaryResponse, summary="获取文档摘要")
def get_summary(task_id: str, session: Session = Depends(get_db)):
    """
    获取文档摘要
    :param task_id:
    :param session:
    :return:
    """
    return SummaryService.get_by_task(task_id, session)


@summary_router.post("/tasks/{task_id}/summary/regenerate", response_model=SummaryResponse, summary="重新生成文档摘要")
def regenerate_summary(task_id: str, session: Session = Depends(get_db)):
    """
    重新生成文档摘要
    :param task_id:
    :param session:
    :return:
    """
    return SummaryService.regenerate_for_task(task_id, session)
