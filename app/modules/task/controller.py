import threading
import uuid
from datetime import datetime
from typing import List

from app.modules.task.schema import ManagedDocumentsListResponse, TaskCreate, TaskResponse
from app.modules.task.model import Task, KnowledgeBase
from fastapi import APIRouter, Depends, Query
from app.modules.task.service import TasksService
from sqlalchemy.orm import Session
from app.core.db import get_db, SessionLocal

router = APIRouter()


@router.post("/tasks", response_model=TaskResponse, summary="创建解析任务")
def create_task(task: TaskCreate, session: Session = Depends(get_db)):
    """
    创建任务
    """
    return TasksService.create_task(task, session)


@router.get("/tasks", response_model=List[TaskResponse], summary="获取任务列表")
def get_tasks(session: Session = Depends(get_db)):
    """
    获取所有任务
    """
    return TasksService.get_task(session)

@router.get("/documents/managed", response_model=ManagedDocumentsListResponse, summary="获取文档管理列表")
def get_managed_documents(
    kb_id: str | None = Query(None, description="按知识库 ID 过滤。"),
    keyword: str | None = Query(None, description="按文件名关键字模糊搜索。"),
    page: int = Query(1, ge=1, description="分页页码，从 1 开始。"),
    page_size: int = Query(20, ge=1, le=100, description="每页返回条数。"),
    session: Session = Depends(get_db)
):
    """
    获取文档管理列表接口。
    这个接口返回已完成解析的文档任务，并在后端完成筛选、搜索和分页，供文档管理页直接展示和下线操作。
    """
    return TasksService.get_managed_documents(session, kb_id=kb_id, keyword=keyword, page=page, page_size=page_size)

@router.get("/tasks/queue-status", summary="获取解析队列状态")
def get_queue_status():
    """
    获取解析队列状态
    """
    return TasksService.get_queue_status()


@router.get("/tasks/{task_id}", response_model=TaskResponse, summary="获取任务详情")
def get_task(task_id: str, session: Session = Depends(get_db)):
    """
    根据id获取任务
    """
    return TasksService.get_task_by_id(task_id, session)


@router.put("/tasks/{task_id}/start", summary="手动开始单个任务")
def start_task(task_id: str, session: Session = Depends(get_db)):
    """
    开始任务
    """
    task = TasksService.start_task(task_id, session)
    return task

@router.put("/tasks/{task_id}/finish", summary="手动结束单个任务")
def finish_task(task_id: str, session: Session = Depends(get_db)):
    """
    结束任务
    """
    task = TasksService.finish_task(task_id, session)
    return task

@router.put("/tasks/run", summary="执行单个任务")
def run_task(task_id: str, session: Session = Depends(get_db)):
    """
    运行任务
    """
    task = TasksService.run_task(task_id, session)
    return task

@router.delete("/tasks/{task_id}", summary="删除任务")
def delete_task(task_id: str, session: Session = Depends(get_db)):
    """
    删除任务
    """
    task = TasksService.delete_task(task_id, session)
    return task

@router.get("/dashboard", summary="获取仪表盘概览")
def dashboard(session: Session = Depends(get_db)):
    """
    获取仪表盘数据
    """
    return TasksService.get_dashboard(session)

@router.get("/dashboard/trend", summary="获取仪表盘趋势")
def get_trend(session: Session = Depends(get_db)):
    """
    获取过去24小时趋势数据
    """
    return TasksService.get_trend(session)

@router.get("/tasks/by_kb/{kb_id}", summary="按知识库获取任务")
def get_tasks_by_kb(kb_id: str, session: Session = Depends(get_db)):
    """
    根据知识库id获取任务
    """
    return TasksService.get_tasks_by_kb(kb_id, session)

@router.get("/tasks/{task_id}/chunks", summary="分页获取任务切片")
def get_chunks(
    task_id: str,
    page: int = 1,
    page_size: int = 10,
    session: Session = Depends(get_db)
):
    """
    获取任务下的所有分块
    """
    return TasksService.get_chunks(task_id, session, page, page_size)

@router.post("/tasks/start-queue", summary="启动解析队列")
def start_queue():
    """
    启动队列
    """
    if TasksService.worker_running:
        return {"msg": "队列已经在运行"}

    thread = threading.Thread(
        target=TasksService.worker,
        args=(SessionLocal,),
        daemon=True
    )
    thread.start()

    return {"msg": "队列启动成功"}

@router.post("/tasks/stop-queue", summary="停止解析队列")
def stop_queue():
    """
    停止队列
    """
    TasksService.worker_running = False
    return {"msg": "队列已停止"}

# 测试数据接口
@router.get("/mock", summary="生成测试任务数据")
def mock_data(session: Session = Depends(get_db)):
    """
    说明：mock_data 函数，处理当前模块的对应业务步骤。
    """
    TasksService.seed_tasks(session)
    return {"msg": "mock data ok"}

@router.get("/init-kb", summary="初始化默认知识库")
def init_kb(session: Session = Depends(get_db)):
    """
    说明：init_kb 函数，处理当前模块的对应业务步骤。
    """
    now = datetime.now()

    data = [
        ("企业资料库", "用于存储企业资料"),
        ("合同知识库", "用于存储合同知识"),
        ("产品知识库", "用于存储产品知识"),
        ("制度知识库", "用于存储制度知识"),
    ]

    for name, description in data:
        # 用 name 判断是否已存在（避免重复）
        exists = session.query(KnowledgeBase).filter_by(name=name).first()

        if not exists:
            session.add(KnowledgeBase(
                id=str(uuid.uuid4()),
                name=name,
                description=description,
                created_at=now
            ))

    session.commit()
    return {"msg": "ok"}
