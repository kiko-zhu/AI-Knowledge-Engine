import json
import uuid
from datetime import datetime

from fastapi import HTTPException
from loguru import logger

from app.core.llm import summarize_markdown
from app.modules.summary.model import DocumentSummary
from app.modules.task.model import Task


class SummaryService:
    """
    说明：SummaryService 类，封装当前模块的数据结构或业务逻辑。
    """
    @classmethod
    def _format_dt(cls, value: datetime | None) -> str:
        """
        说明：_format_dt 函数，处理当前模块的对应业务步骤。
        """
        if not value:
            return ""
        return value.isoformat(timespec="seconds")

    @classmethod
    def _serialize(cls, summary: DocumentSummary):
        """
        说明：_serialize 函数，处理当前模块的对应业务步骤。
        """
        try:
            keywords = json.loads(summary.keywords_json) if summary.keywords_json else []
        except Exception:
            keywords = []

        try:
            sections = json.loads(summary.sections_json) if summary.sections_json else []
        except Exception:
            sections = []

        return {
            "task_id": summary.task_id,
            "file_name": summary.file_name or "",
            "status": summary.status,
            "summary": summary.summary_text,
            "keywords": keywords,
            "sections": sections,
            "error_message": summary.error_message,
            "created_at": cls._format_dt(summary.created_at),
            "updated_at": cls._format_dt(summary.updated_at)
        }

    @classmethod
    def get_by_task(cls, task_id: str, session):
        """
            获取文档摘要
        :param task_id:
        :param session:
        :return:
        """
        summary = session.query(DocumentSummary).filter(DocumentSummary.task_id == task_id).first()
        if not summary:
            raise HTTPException(status_code=404, detail="Summary not found")
        return cls._serialize(summary)

    @classmethod
    def upsert_for_task(cls, task: Task, content: str, session):
        """
            为某个文档任务生成或更新文章摘要
        :param task:任务
        :param content:
        :param session:
        :return:
        """
        now = datetime.now()
        summary = session.query(DocumentSummary).filter(DocumentSummary.task_id == task.id).first()
        if not summary:
            summary = DocumentSummary(
                id=str(uuid.uuid4()),
                task_id=task.id,
                file_name=task.file_name,
                created_at=now,
                updated_at=now,
                status="processing"
            )
            session.add(summary)
            session.commit()
            session.refresh(summary)

        summary.file_name = task.file_name
        summary.status = "processing"
        summary.error_message = None
        summary.updated_at = now
        session.commit()

        try:
            raw = summarize_markdown(content)
            parsed = json.loads(raw)

            summary.summary_text = parsed.get("summary") or ""
            summary.keywords_json = json.dumps(parsed.get("keywords") or [], ensure_ascii=False)
            summary.sections_json = json.dumps(parsed.get("sections") or [], ensure_ascii=False)
            summary.status = "success"
            summary.error_message = None
        except Exception as exc:
            logger.warning(f"summary generation failed for task {task.id}: {exc}")
            summary.summary_text = None
            summary.keywords_json = json.dumps([], ensure_ascii=False)
            summary.sections_json = json.dumps([], ensure_ascii=False)
            summary.status = "failed"
            summary.error_message = str(exc)

        summary.updated_at = datetime.now()
        session.commit()
        session.refresh(summary)
        return summary

    @classmethod
    def regenerate_for_task(cls, task_id: str, session):
        """
            重新生成文档摘要
        :param task_id:
        :param session:
        :return:
        """
        task = session.query(Task).filter(Task.id == task_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="任务未找到")
        if task.status != "success":
            raise HTTPException(status_code=400, detail="在生成摘要之前，任务必须先完成。")

        from app.parsers.md_parser import MarkdownParser

        parser = MarkdownParser()
        content = parser.parse(task.file_path)
        summary = cls.upsert_for_task(task, content, session)
        return cls._serialize(summary)
