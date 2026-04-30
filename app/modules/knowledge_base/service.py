import uuid
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import func, inspect, text

from app.modules.task.model import DocumentChunk, KnowledgeBase, Task


class KbaseService:
    """
    说明：KbaseService 类，封装当前模块的数据结构或业务逻辑。
    """
    @classmethod
    def ensure_schema(cls, engine):
        """
        给已有数据库补 knowledge_bases.enabled 列。
        create_all 只能建新表，不能给老表追加列，这里做一次轻量兼容。
        """
        inspector = inspect(engine)
        if "knowledge_bases" not in inspector.get_table_names():
            return

        columns = {column["name"] for column in inspector.get_columns("knowledge_bases")}
        if "enabled" in columns:
            return

        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE knowledge_bases ADD COLUMN enabled BOOLEAN DEFAULT 1"))

    @classmethod
    def get_kbs(cls, session):
        """
        返回所有知识库基础信息，供任务创建、问答配置和知识库管理页面使用。
        """
        return session.query(KnowledgeBase).order_by(KnowledgeBase.created_at.desc(), KnowledgeBase.id.desc()).all()

    @classmethod
    def get_kb_or_404(cls, kb_id, session):
        """
        根据知识库 ID 查询知识库；不存在时直接抛 404，统一给接口层复用。
        """
        kb = session.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
        if not kb:
            raise HTTPException(status_code=404, detail="知识库不存在")
        return kb

    @classmethod
    def create_kb(cls, data, session):
        """
        创建知识库。新知识库默认启用，可直接参与后续检索和问答。
        """
        kb = KnowledgeBase(
            id=str(uuid.uuid4()),
            name=data.name,
            description=data.description,
            enabled=True,
            created_at=datetime.now()
        )
        session.add(kb)
        session.commit()
        session.refresh(kb)
        return kb

    @classmethod
    def update_enabled(cls, kb_id, enabled, session):
        """
        更新知识库启停状态。
        启用时允许该知识库参与检索；停用后搜索和问答默认不会命中这个知识库。
        """
        kb = cls.get_kb_or_404(kb_id, session)
        kb.enabled = bool(enabled)
        session.add(kb)
        session.commit()
        session.refresh(kb)
        return kb

    @classmethod
    def get_kb_stats(cls, session):
        """
        聚合每个知识库下的文档数和切片数，供知识库卡片页直接展示。
        文档数按 tasks 聚合，切片数按 document_chunks 关联 tasks 后聚合。
        """
        task_counts = (
            session.query(
                Task.knowledge_base_id.label("kb_id"),
                func.count(Task.id).label("document_count")
            )
            .group_by(Task.knowledge_base_id)
            .subquery()
        )

        chunk_counts = (
            session.query(
                Task.knowledge_base_id.label("kb_id"),
                func.count(DocumentChunk.id).label("chunk_count")
            )
            .join(DocumentChunk, DocumentChunk.task_id == Task.id)
            .group_by(Task.knowledge_base_id)
            .subquery()
        )

        rows = (
            session.query(
                KnowledgeBase.id,
                KnowledgeBase.name,
                KnowledgeBase.description,
                KnowledgeBase.enabled,
                KnowledgeBase.created_at,
                func.coalesce(task_counts.c.document_count, 0).label("document_count"),
                func.coalesce(chunk_counts.c.chunk_count, 0).label("chunk_count")
            )
            .outerjoin(task_counts, task_counts.c.kb_id == KnowledgeBase.id)
            .outerjoin(chunk_counts, chunk_counts.c.kb_id == KnowledgeBase.id)
            .order_by(KnowledgeBase.created_at.desc(), KnowledgeBase.id.desc())
            .all()
        )

        return [
            {
                "id": row.id,
                "name": row.name,
                "description": row.description,
                "enabled": bool(row.enabled),
                "created_at": row.created_at,
                "document_count": row.document_count,
                "chunk_count": row.chunk_count,
            }
            for row in rows
        ]

    @classmethod
    def extract_section(cls, content: str):
        """
        从 chunk 文本中提取 Markdown 章节名，供知识库切片审查页展示和筛选理解。
        """
        for line in (content or "").splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                return stripped.replace("#", "").strip()
        return None

    @classmethod
    def get_kb_chunks(cls, kb_id, session, page=1, page_size=20):
        """
        分页查询某个知识库下的所有切片。
        这个接口服务于知识库维度的切片审查页面，不再把“查看全部切片”错误映射到单任务视角。
        """
        kb = cls.get_kb_or_404(kb_id, session)

        query = (
            session.query(DocumentChunk, Task)
            .join(Task, DocumentChunk.task_id == Task.id)
            .filter(Task.knowledge_base_id == kb_id)
        )

        total = query.count()
        rows = (
            query.order_by(Task.created_at.desc(), Task.id.desc(), DocumentChunk.chunk_index.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

        return {
            "kb_id": kb.id,
            "kb_name": kb.name,
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": [
                {
                    "task_id": task.id,
                    "file_name": task.file_name,
                    "file_path": task.file_path,
                    "chunk_index": chunk.chunk_index,
                    "section": cls.extract_section(chunk.content),
                    "content": chunk.content,
                    "length": len(chunk.content or ""),
                    "created_at": chunk.created_at,
                }
                for chunk, task in rows
            ]
        }

    @classmethod
    def get_kb_documents(cls, kb_id, session, page=1, page_size=20):
        """
        分页查询某个知识库下的文档任务列表。
        这个接口服务于知识库维度的文档页，让“文档数”入口能落到正确的聚合视角。
        """
        kb = cls.get_kb_or_404(kb_id, session)

        chunk_counts = (
            session.query(
                DocumentChunk.task_id.label("task_id"),
                func.count(DocumentChunk.id).label("chunk_count")
            )
            .group_by(DocumentChunk.task_id)
            .subquery()
        )

        query = (
            session.query(
                Task.id.label("task_id"),
                Task.file_name,
                Task.file_path,
                Task.status,
                Task.progress,
                Task.created_at,
                Task.updated_at,
                func.coalesce(chunk_counts.c.chunk_count, 0).label("chunk_count")
            )
            .outerjoin(chunk_counts, chunk_counts.c.task_id == Task.id)
            .filter(Task.knowledge_base_id == kb_id)
        )

        total = query.count()
        rows = (
            query.order_by(Task.created_at.desc(), Task.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

        return {
            "kb_id": kb.id,
            "kb_name": kb.name,
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": [
                {
                    "task_id": row.task_id,
                    "file_name": row.file_name,
                    "file_path": row.file_path,
                    "status": row.status,
                    "progress": row.progress or 0,
                    "chunk_count": row.chunk_count,
                    "created_at": row.created_at,
                    "updated_at": row.updated_at,
                }
                for row in rows
            ]
        }

    @classmethod
    def delete_kb(cls, kb_id, session):
        """
        删除知识库本身。
        这里只处理知识库记录，不联动删除任务和切片数据。
        """
        kb = cls.get_kb_or_404(kb_id, session)
        session.delete(kb)
        session.commit()
        return kb
