import uuid
import re
import random
from datetime import date
from datetime import datetime, timedelta
from loguru import logger
from app.core.embedding import get_embedding
from app.modules.task.model import Task, KnowledgeBase, DocumentChunk
from fastapi import HTTPException
from app.core.enums import TaskStatus
from app.parsers.chunking import split_for_rag
from app.parsers.factory import get_parser
from app.parsers.utils import validate_file
from app.parsers.md_parser import MarkdownParser
from app.modules.summary.service import SummaryService
from app.modules.knowledge_card.service import KnowledgeCardService
import json
from sqlalchemy import func, inspect, text


def extract_json(text):
    """
    说明：extract_json 函数，处理当前模块的对应业务步骤。
    """
    match = re.search(r"\{.*\}", text, re.S)
    if match:
        return match.group()
    return None


class TasksService:
    """
    说明：TasksService 类，封装当前模块的数据结构或业务逻辑。
    """
    worker_running = False  # 队列是否在运行

    @classmethod
    def get_queue_status(cls):
        """
        返回当前解析队列是否处于运行状态，供前端启停按钮判断使用。
        """
        return {"running": cls.worker_running}

    @classmethod
    def ensure_schema(cls, engine):
        """
        轻量兼容已有 sqlite 库。create_all 不会给老表补列，这里只补 tasks.progress。
        """
        inspector = inspect(engine)
        if "tasks" not in inspector.get_table_names():
            return

        columns = {column["name"] for column in inspector.get_columns("tasks")}
        if "progress" in columns:
            return

        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE tasks ADD COLUMN progress INTEGER DEFAULT 0"))

    @classmethod
    def sync_task_state(cls, task, session, *, status=None, progress=None, error_message=None):
        """
        同步更新任务状态、进度和错误信息。
        这个函数负责统一写库，保证轮询时能看到最新任务进展。
        """
        changed = False

        if status is not None and task.status != status:
            task.status = status
            changed = True

        if progress is not None:
            bounded_progress = max(0, min(100, int(progress)))
            current_progress = task.progress or 0
            if current_progress != bounded_progress:
                task.progress = bounded_progress
                changed = True

        if error_message is not None and task.error_message != error_message:
            task.error_message = error_message
            changed = True

        if not changed:
            return task

        task.updated_at = datetime.now()
        session.add(task)
        session.commit()
        session.refresh(task)
        return task

    @classmethod
    def create_task(cls, new_task, session):
        """
        创建新的解析任务。
        这里只写入任务记录，不会立即执行解析流程。
        """
        kb = session.query(KnowledgeBase).filter_by(id=new_task.knowledge_base_id).first()
        if not kb:
            raise HTTPException(404, "知识库不存在")
        task = Task(
            id=str(uuid.uuid4()),
            file_name=new_task.file_name,
            file_path=new_task.file_path,
            status="pending",
            progress=0,
            result=None,
            error_message=None,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            knowledge_base_id=new_task.knowledge_base_id
        )
        session.add(task)
        session.commit()
        session.refresh(task)
        return task

    @classmethod
    def get_task(cls, session):
        """
        返回全部任务列表，并补齐每个任务当前的切片数量。
        这个接口给文档中心、仪表板等页面复用。
        """
        tasks = session.query(Task).order_by(
            Task.created_at.desc(),
            Task.id.desc()
        ).all()
        cls.attach_chunk_counts(tasks, session)
        return tasks

    @classmethod
    def get_task_by_id(cls, task_id, session):
        """
        根据任务 ID 获取单个任务详情，并补齐切片数量。
        """
        task = session.query(Task).filter(Task.id == task_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        cls.attach_chunk_counts([task], session)
        return task

    @classmethod
    def attach_chunk_counts(cls, tasks, session):
        """
        给任务对象补充 chunk_count 计算字段。
        这里不改数据库结构，只在接口返回前附着当前统计值。
        """
        if not tasks:
            return tasks

        task_ids = [task.id for task in tasks]
        rows = (
            session.query(
                DocumentChunk.task_id,
                func.count(DocumentChunk.id).label("chunk_count")
            )
            .filter(DocumentChunk.task_id.in_(task_ids))
            .group_by(DocumentChunk.task_id)
            .all()
        )
        chunk_map = {row.task_id: int(row.chunk_count or 0) for row in rows}

        for task in tasks:
            setattr(task, "chunk_count", chunk_map.get(task.id, 0))

        return tasks

    @classmethod
    def start_task(cls, task_id, session):
        """
        手动把单个任务切到处理中状态。
        这个接口主要用于保留单任务启动能力，不是批量队列入口。
        """
        task = cls.get_task_by_id(task_id, session)
        if task.status != TaskStatus.PENDING:
            raise HTTPException(status_code=400, detail="当前任务状态不允许开始")
        return cls.sync_task_state(task, session, status=TaskStatus.PROCESSING, progress=0)

    @classmethod
    def finish_task(cls, task_id, session):
        """
        手动把单个任务切到完成状态。
        这个接口主要用于保留状态控制能力。
        """
        task = cls.get_task_by_id(task_id, session)
        if task.status != TaskStatus.PROCESSING:
            raise HTTPException(status_code=400, detail="当前任务状态不允许结束")
        return cls.sync_task_state(task, session, status=TaskStatus.SUCCESS, progress=100)

    @classmethod
    def run_task(cls, task_id, session):
        """
        执行单个解析任务全流程。
        包括读取文件、切片、向量化、摘要生成和知识卡片生成。
        """
        task = cls.get_task_by_id(task_id, session)

        if task.status in [TaskStatus.SUCCESS, TaskStatus.PROCESSING]:
            raise HTTPException(status_code=400, detail="当前任务状态不允许运行")

        # 任务刚开始时先写入处理中和初始进度，前端轮询可以立刻看到状态变化。
        cls.sync_task_state(task, session, status=TaskStatus.PROCESSING, progress=5, error_message=None)
        task.result = None
        session.add(task)
        session.commit()

        try:
            # 清理旧数据
            session.query(DocumentChunk).filter_by(task_id=task.id).delete()
            session.commit()
            cls.sync_task_state(task, session, progress=10)

            # 解析
            parser = MarkdownParser()
            content = parser.parse(task.file_path)
            cls.sync_task_state(task, session, progress=20)

            # 切片
            chunks = split_for_rag(content)
            cls.sync_task_state(task, session, progress=30)

            objs = []
            valid_chunks = [chunk for chunk in chunks if chunk.strip()]
            total_chunks = len(valid_chunks)
            progress_start = 35
            progress_end = 80

            for processed_index, chunk in enumerate(valid_chunks):

                # 不在入库前做硬截断。
                # 否则即使 chunking 已经按语义切好了，
                # 这里也会把同一条业务规则从中间砍断，导致“3. 结果字段”这类内容丢失。
                # 长度控制应由 chunking 阶段负责，而不是在持久化前直接截字符。

                try:
                    embedding = get_embedding(chunk)
                    embedding = json.dumps(embedding)
                except Exception as e:
                    logger.warning(f"embedding失败，跳过: {e}")
                    continue

                chunk_obj = DocumentChunk(
                    id=str(uuid.uuid4()),
                    task_id=task.id,
                    content=chunk,
                    embedding=embedding,
                    chunk_index=processed_index,
                    created_at = datetime.now()
                )
                objs.append(chunk_obj)

                if total_chunks > 0:
                    ratio = (processed_index + 1) / total_chunks
                    chunk_progress = progress_start + ratio * (progress_end - progress_start)
                    cls.sync_task_state(task, session, progress=chunk_progress)

            # 批量入库
            if objs:
                session.bulk_save_objects(objs)

            session.commit()
            cls.sync_task_state(task, session, progress=85)

            # 自动生成文档级摘要。这里作为知识沉淀能力的一部分，
            # 即使摘要失败也不反向打断文档解析主流程。
            SummaryService.upsert_for_task(task, content, session)
            cls.sync_task_state(task, session, progress=92)
            KnowledgeCardService.upsert_for_task(task, content, session)
            cls.sync_task_state(task, session, progress=97)

            # 成功
            task.status = TaskStatus.SUCCESS
            task.progress = 100
            task.error_message = None

        except Exception as e:
            logger.exception("任务执行失败")
            task.status = TaskStatus.FAILED
            task.error_message = str(e)

        finally:
            task.updated_at = datetime.now()
            session.commit()

        return task

    @classmethod
    def get_managed_documents(cls, session, kb_id: str | None = None, keyword: str | None = None, page: int = 1, page_size: int = 20):
        """
        返回文档管理页需要的“已完成解析文档”列表。
        这里在后端完成知识库筛选、文件名搜索和分页，避免前端全量拉取后再做本地过滤。
        """
        query = session.query(Task).filter(Task.status == TaskStatus.SUCCESS)

        if kb_id:
            query = query.filter(Task.knowledge_base_id == kb_id)

        normalized_keyword = (keyword or "").strip()
        if normalized_keyword:
            query = query.filter(Task.file_name.ilike(f"%{normalized_keyword}%"))

        total = query.count()
        tasks = (
            query.order_by(Task.updated_at.desc(), Task.created_at.desc(), Task.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        cls.attach_chunk_counts(tasks, session)

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": [
                {
                    "task_id": task.id,
                    "file_name": task.file_name,
                    "file_path": task.file_path,
                    "knowledge_base_id": task.knowledge_base_id,
                    "status": task.status,
                    "progress": task.progress or 0,
                    "chunk_count": getattr(task, "chunk_count", 0),
                    "created_at": task.created_at,
                    "updated_at": task.updated_at,
                }
                for task in tasks
            ]
        }

    @classmethod
    def get_dashboard(cls, session):
        """
        说明：get_dashboard 函数，处理当前模块的对应业务步骤。
        """
        total_tasks = session.query(Task).count()
        pending = session.query(Task).filter(
            Task.status == TaskStatus.PENDING
        ).count()
        processing = session.query(Task).filter(
            Task.status == TaskStatus.PROCESSING
        ).count()
        success = session.query(Task).filter(
            Task.status == TaskStatus.SUCCESS
        ).count()
        failed = session.query(Task).filter(
            Task.status == TaskStatus.FAILED
        ).count()
        today_start = datetime.combine(date.today(), datetime.min.time())
        tomorrow_start = today_start + timedelta(days=1)
        today_tasks = session.query(Task).filter(
            Task.created_at >= today_start,
            Task.created_at < tomorrow_start
        ).count()
        success_rate = success / total_tasks if total_tasks > 0 else 0
        return {
            "total": total_tasks,
            "pending": pending,
            "processing": processing,
            "success": success,
            "failed": failed,
            "today_count": today_tasks,
            "success_rate": success_rate
        }

    @classmethod
    def get_trend(cls, session):
        """
        说明：get_trend 函数，处理当前模块的对应业务步骤。
        """
        now = datetime.now()
        start_time = now - timedelta(hours=24)

        tasks = session.query(Task).filter(
            Task.created_at >= start_time
        ).all()

        trend_map = {}

        # 初始化24小时桶
        for i in range(24):
            bucket_time = (start_time + timedelta(hours=i)).replace(
                minute=0, second=0, microsecond=0
            )
            bucket_key = bucket_time.strftime("%Y-%m-%d %H:00")

            trend_map[bucket_key] = {
                "time": bucket_key,
                "queued": 0,
                "success": 0,
                "failed": 0
            }

        # 遍历任务归类
        for task in tasks:
            if not task.created_at:
                continue

            bucket_time = task.created_at.replace(
                minute=0, second=0, microsecond=0
            )
            bucket_key = bucket_time.strftime("%Y-%m-%d %H:00")

            if bucket_key not in trend_map:
                continue

            trend_map[bucket_key]["queued"] += 1

            if task.status == TaskStatus.SUCCESS:
                trend_map[bucket_key]["success"] += 1
            elif task.status == TaskStatus.FAILED:
                trend_map[bucket_key]["failed"] += 1

        return sorted(trend_map.values(), key=lambda x: x["time"])

    @classmethod
    def seed_tasks(cls, session):
        """
        说明：seed_tasks 函数，处理当前模块的对应业务步骤。
        """
        now = datetime.now()

        # 保证有知识库（避免外键报错）
        kb = session.query(KnowledgeBase).first()
        if not kb:
            kb = KnowledgeBase(
                id=str(uuid.uuid4()),
                name="默认知识库",
                created_at=now
            )
            session.add(kb)
            session.commit()
            session.refresh(kb)

        # 清空旧数据（可选）
        session.query(Task).delete()
        session.commit()

        # 造数据
        for i in range(24):
            for _ in range(random.randint(1, 3)):
                created_time = now - timedelta(hours=i)

                status = random.choice([
                    TaskStatus.PENDING,
                    TaskStatus.PROCESSING,
                    TaskStatus.SUCCESS,
                    TaskStatus.FAILED
                ])

                task = Task(
                    id=str(uuid.uuid4()),
                    file_name=f"test_{i}.md",
                    file_path=f"/mock/path/test_{i}.md",
                    status=status,
                    progress=100 if status == TaskStatus.SUCCESS else 0,
                    result=None,
                    error_message=None,
                    created_at=created_time,
                    updated_at=created_time,
                    knowledge_base_id=kb.id
                )

                session.add(task)

        session.commit()

    @classmethod
    def get_tasks_by_kb(cls, kb_id, session):
        """
        说明：get_tasks_by_kb 函数，处理当前模块的对应业务步骤。
        """
        return session.query(Task).filter(Task.knowledge_base_id == kb_id).all()

    @classmethod
    def worker(cls, session_factory):
        """
        运行解析队列 worker。
        队列只处理当前批次 pending 任务，清空后自动退出，避免新上传任务被立即消费。
        """
        cls.worker_running = True

        try:
            while cls.worker_running:
                session = session_factory()

                try:
                    task = session.query(Task).filter(
                        Task.status == TaskStatus.PENDING
                    ).order_by(Task.created_at.asc()).first()

                    # 队列启动后只处理当前批次任务。没有待处理任务就自动停止，
                    # 避免 worker 常驻导致后续新上传任务被立即消费。
                    if not task:
                        cls.worker_running = False
                        break

                    print(f"开始处理任务: {task.id}")

                    cls.run_task(task.id, session)

                except Exception as e:
                    print("worker error:", e)

                finally:
                    session.close()
        finally:
            cls.worker_running = False

    @classmethod
    def delete_task(cls, task_id, session):
        """
        删除任务记录。
        文档管理页里的“下线”当前复用这个逻辑。
        """
        task = session.query(Task).filter(Task.id == task_id).first()
        if task:
            session.delete(task)
            session.commit()
            return True
        return False

    @classmethod
    def extract_section(cls, content: str):
        """
        从 chunk 文本里提取章节标题，供切片列表页显示。
        """
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("#"):
                return line.replace("#", "").strip()
        return None

    @classmethod
    def get_chunks(cls, task_id, session, page=1, page_size=10):
        """
        分页返回某个任务下的切片列表，服务于单任务切片详情页。
        """
        query = session.query(DocumentChunk) \
            .filter_by(task_id=task_id)

        total = query.count()

        chunks = query \
            .order_by(DocumentChunk.chunk_index.asc()) \
            .offset((page - 1) * page_size) \
            .limit(page_size) \
            .all()

        task = session.query(Task).filter_by(id=task_id).first()

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": [
                {
                    "content": c.content,
                    "length": len(c.content),
                    "chunk_index": c.chunk_index,
                    "kb_id": task.knowledge_base_id if task else None,
                    "file_name": task.file_name if task else None,
                    "section": cls.extract_section(c.content),
                }
                for c in chunks
            ]
        }
