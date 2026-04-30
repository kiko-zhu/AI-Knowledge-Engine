import json
import uuid
from datetime import datetime

from fastapi import HTTPException
from loguru import logger

from app.core.llm import extract_knowledge_cards
from app.modules.knowledge_card.model import KnowledgeCardSet
from app.modules.task.model import Task


class KnowledgeCardService:
    """
    说明：KnowledgeCardService 类，封装当前模块的数据结构或业务逻辑。
    """
    @classmethod
    def _format_dt(cls, value: datetime | None) -> str:
        """
        格式化日期时间
        :param value:
        :return:
        """
        if not value:
            return ""
        return value.isoformat(timespec="seconds")

    @classmethod
    def _serialize(cls, card_set: KnowledgeCardSet):
        """
        序列化知识卡片
        :param card_set:
        :return:
        """
        try:
            cards = json.loads(card_set.cards_json) if card_set.cards_json else []
        except Exception:
            cards = []

        return {
            "task_id": card_set.task_id,
            "file_name": card_set.file_name or "",
            "status": card_set.status,
            "cards": cards,
            "error_message": card_set.error_message,
            "created_at": cls._format_dt(card_set.created_at),
            "updated_at": cls._format_dt(card_set.updated_at)
        }

    @classmethod
    def get_by_task(cls, task_id: str, session):
        """
        获取知识卡片
        :param task_id:
        :param session:
        :return:
        """
        card_set = session.query(KnowledgeCardSet).filter(KnowledgeCardSet.task_id == task_id).first()
        if not card_set:
            raise HTTPException(status_code=404, detail="Knowledge cards not found")
        return cls._serialize(card_set)

    @classmethod
    def upsert_for_task(cls, task: Task, content: str, session):
        """
            为某个文档任务生成或更新知识卡片
        :param task:任务
        :param content:
        :param session:
        :return:
        """
        now = datetime.now()
        card_set = session.query(KnowledgeCardSet).filter(KnowledgeCardSet.task_id == task.id).first()
        if not card_set:
            card_set = KnowledgeCardSet(
                id=str(uuid.uuid4()),
                task_id=task.id,
                file_name=task.file_name,
                created_at=now,
                updated_at=now,
                status="processing"
            )
            session.add(card_set)
            session.commit()
            session.refresh(card_set)

        card_set.file_name = task.file_name
        card_set.status = "processing"
        card_set.error_message = None
        card_set.updated_at = now
        session.commit()

        try:
            raw = extract_knowledge_cards(content)
            parsed = json.loads(raw)
            cards = parsed.get("cards") or []

            card_set.cards_json = json.dumps(cards, ensure_ascii=False)
            card_set.status = "success"
            card_set.error_message = None
        except Exception as exc:
            logger.warning(f"knowledge card generation failed for task {task.id}: {exc}")
            card_set.cards_json = json.dumps([], ensure_ascii=False)
            card_set.status = "failed"
            card_set.error_message = str(exc)

        card_set.updated_at = datetime.now()
        session.commit()
        session.refresh(card_set)
        return card_set

    @classmethod
    def regenerate_for_task(cls, task_id: str, session):
        """
            重新生成知识卡片
        :param task_id:
        :param session:
        :return:
        """
        task = session.query(Task).filter(Task.id == task_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        if task.status != "success":
            raise HTTPException(status_code=400, detail="Task must be successful before generating knowledge cards")

        from app.parsers.md_parser import MarkdownParser

        parser = MarkdownParser()
        content = parser.parse(task.file_path)
        card_set = cls.upsert_for_task(task, content, session)
        return cls._serialize(card_set)
