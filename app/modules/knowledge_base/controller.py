from typing import List

from fastapi import APIRouter, Body, Depends, Path
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.modules.knowledge_base.service import KbaseService
from app.modules.task.schema import (
    KnowledgeBaseCreate,
    KnowledgeBaseChunksResponse,
    KnowledgeBaseDocumentsResponse,
    KnowledgeBaseEnabledUpdate,
    KnowledgeBaseResponse,
    KnowledgeBaseStatsResponse,
)

kbs_router = APIRouter()


@kbs_router.post(
    "/kbs",
    response_model=KnowledgeBaseResponse,
    summary="创建知识库",
    description="创建一个新的知识库，默认启用，可直接用于上传任务、检索和问答。"
)
def create_kb(
    kb: KnowledgeBaseCreate = Body(..., description="知识库创建参数，包括名称和可选描述。"),
    session: Session = Depends(get_db)
):
    """
    创建知识库接口。
    这个接口负责接收前端新建知识库请求，并把数据交给业务层落库。
    """
    return KbaseService.create_kb(kb, session)


@kbs_router.get(
    "/kbs",
    response_model=List[KnowledgeBaseResponse],
    summary="获取知识库列表",
    description="返回系统中的全部知识库基础信息，包含启停状态。"
)
def get_kbs(session: Session = Depends(get_db)):
    """
    获取知识库列表接口。
    这个接口用于给任务创建、问答配置和知识库页面提供下拉列表数据。
    """
    return KbaseService.get_kbs(session)


@kbs_router.get(
    "/kbs/stats",
    response_model=List[KnowledgeBaseStatsResponse],
    summary="获取知识库统计",
    description="返回每个知识库的文档数量、切片数量和启停状态，供知识库卡片页展示。"
)
def get_kb_stats(session: Session = Depends(get_db)):
    """
    获取知识库统计接口。
    这个接口专门给前端知识库卡片页使用，避免前端自己拼任务和切片统计。
    """
    return KbaseService.get_kb_stats(session)


@kbs_router.get(
    "/kbs/{kb_id}/documents",
    response_model=KnowledgeBaseDocumentsResponse,
    summary="分页获取知识库文档",
    description="按知识库维度分页返回文档任务列表，供知识库文档页展示。"
)
def get_kb_documents(
    kb_id: str = Path(..., description="要查询的知识库 ID。"),
    page: int = 1,
    page_size: int = 20,
    session: Session = Depends(get_db)
):
    """
    获取知识库文档接口。
    这个接口提供知识库维度的文档列表，方便从知识库卡片直接进入文档视角查看任务状态和切片数量。
    """
    return KbaseService.get_kb_documents(kb_id, session, page, page_size)


@kbs_router.get(
    "/kbs/{kb_id}/chunks",
    response_model=KnowledgeBaseChunksResponse,
    summary="分页获取知识库切片",
    description="按知识库维度分页返回所有文档切片，供知识库切片审查页展示。"
)
def get_kb_chunks(
    kb_id: str = Path(..., description="要查询的知识库 ID。"),
    page: int = 1,
    page_size: int = 20,
    session: Session = Depends(get_db)
):
    """
    获取知识库切片接口。
    这个接口提供知识库维度的切片审查能力，方便运营人员查看某个知识库下所有文档的切片结果。
    """
    return KbaseService.get_kb_chunks(kb_id, session, page, page_size)


@kbs_router.put(
    "/kbs/{kb_id}/enabled",
    response_model=KnowledgeBaseResponse,
    summary="更新知识库启停状态",
    description="启用或停用知识库检索能力。停用后，该知识库默认不会参与搜索和问答召回。"
)
def update_kb_enabled(
    kb_id: str = Path(..., description="要更新的知识库 ID。"),
    req: KnowledgeBaseEnabledUpdate = Body(..., description="知识库启停状态更新参数。"),
    session: Session = Depends(get_db)
):
    """
    更新知识库启停状态接口。
    这个接口让前端开关具备真实业务意义，切换后会直接影响后续检索范围。
    """
    return KbaseService.update_enabled(kb_id, req.enabled, session)


@kbs_router.delete(
    "/kbs/{kb_id}",
    response_model=KnowledgeBaseResponse,
    summary="删除知识库",
    description="根据知识库 ID 删除知识库记录。"
)
def delete_kb(
    kb_id: str = Path(..., description="要删除的知识库 ID。"),
    session: Session = Depends(get_db)
):
    """
    删除知识库接口。
    这个接口只删除知识库记录本身，不处理任务和切片的级联清理。
    """
    return KbaseService.delete_kb(kb_id, session)
