from fastapi import FastAPI

from app.modules.file.controller import file_router
from app.modules.evaluation.controller import evaluation_router
from app.modules.evaluation.service import EvaluationService
from app.modules.knowledge_card.controller import knowledge_card_router
from app.modules.knowledge_base.controller import kbs_router
from app.modules.qa.controller import qa_router
from app.modules.search.controller import search_router
from app.modules.summary.controller import summary_router
from app.modules.task.controller import router as task_router
from app.modules.knowledge_base.service import KbaseService
from app.modules.qa.service import QaService
from app.modules.task.service import TasksService
from app.core.db import Base, engine
from app.core.config import settings

# 创建表
Base.metadata.create_all(bind=engine)
KbaseService.ensure_schema(engine)
TasksService.ensure_schema(engine)
QaService.ensure_schema(engine)
EvaluationService.ensure_schema(engine)

app = FastAPI()

# 注册路由
app.include_router(task_router)                     # 任务
app.include_router(file_router)                     # 文件
app.include_router(evaluation_router)               # 评估
app.include_router(knowledge_card_router)           # 知识卡片
app.include_router(kbs_router)                      # 知识库
app.include_router(search_router)                   # 搜索
app.include_router(qa_router)                       # 问答
app.include_router(summary_router)                  # 摘要

# 启动入口
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=True
    )
