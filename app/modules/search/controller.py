# app/modules/search/controller.py
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.modules.search.schema import SearchRequest, SearchResponse
from app.modules.search.service import SearchService

search_router = APIRouter()

@search_router.post("/search", response_model=SearchResponse, summary="执行知识库检索")
def search(req: SearchRequest, session: Session = Depends(get_db)):
    """
    执行知识库检索。
    如果指定 task_id，只在该文档任务内检索；
    否则如果指定 kb_id，只在该知识库内检索；
    否则只检索当前处于 enabled=true 的知识库。
    """
    return SearchService.search(
        query=req.query,
        session=session,
        kb_id=req.kb_id,
        top_k=req.top_k
    )
