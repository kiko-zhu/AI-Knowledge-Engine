import json
import uuid
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import case, func, text

from app.modules.evaluation.model import MessageFeedback, QaLog
from app.modules.qa.model import ConversationMessage


class EvaluationService:
    """
    说明：EvaluationService 类，封装当前模块的数据结构或业务逻辑。
    """
    ANSWER_TYPE_CATALOG = [
        {
            "answer_type": "text",
            "label": "普通文本回答",
            "description": "用于常规问答，直接基于检索片段组织答案。"
        },
        {
            "answer_type": "list",
            "label": "列表型回答",
            "description": "用于“有哪些 / 包含哪些 / 列出”这类问题，按编号列出要点。"
        },
        {
            "answer_type": "file_spec",
            "label": "文件规格型回答",
            "description": "用于文件路径、文件格式、输出文件等字段型问题，优先做规则抽取。"
        },
        {
            "answer_type": "explanation",
            "label": "解释型回答",
            "description": "用于“用中文解释逻辑 / 怎么计算”这类问题，按适用阶段、计算步骤、结果含义、原文依据组织。"
        },
        {
            "answer_type": "teaching",
            "label": "讲解优化型回答",
            "description": "用于“换种更容易理解的说法 / 讲给别人听”这类追问，在事实不变的前提下做表达优化。"
        },
        {
            "answer_type": "workflow_summary",
            "label": "流程总结型回答",
            "description": "用于“整个流程 / 完整流程 / 从输入到输出”这类问题，按流程主线总结输入、处理、补充数据集和输出。"
        },
        {
            "answer_type": "domain_relation",
            "label": "域关系型回答",
            "description": "用于“某个域与其他域是什么关系 / 依赖哪些域 / 被哪些域依赖”这类问题，按域角色、依赖域、关键字段和作用说明。"
        },
        {
            "answer_type": "domain_logic",
            "label": "域逻辑概览型回答",
            "description": "用于“某个域的逻辑是什么 / 主要做什么 / 核心逻辑”这类问题，按输入来源、核心逻辑、时间处理、依赖关系和输出结果总结该域自身。"
        },
        {
            "answer_type": "field_logic",
            "label": "字段逻辑型回答",
            "description": "用于“某域某字段怎么计算 / 怎么处理 / 如何生成”这类问题，锁定目标域和字段，按计算规则、依赖字段、特殊情况和相关输出回答。"
        },
        {
            "answer_type": "diagram",
            "label": "图示型回答",
            "description": "用于“画图 / 图示 / 流程图”这类追问，复用上一轮已确认答案和引用来源，不重新检索事实。"
        }
    ]

    @classmethod
    def ensure_schema(cls, engine):
        """
        为旧库补齐评估日志新增字段。
        这样历史 QA 日志也能逐步切到按答案类型统计的正式评估链路。
        """
        with engine.begin() as conn:
            columns = [row[1] for row in conn.execute(text("PRAGMA table_info(qa_logs)")).fetchall()]
            if "answer_type" not in columns:
                conn.execute(text("ALTER TABLE qa_logs ADD COLUMN answer_type VARCHAR"))

    @classmethod
    def _format_dt(cls, value: datetime | None) -> str:
        """
        说明：_format_dt 函数，处理当前模块的对应业务步骤。
        """
        if not value:
            return ""
        return value.isoformat(timespec="seconds")

    @classmethod
    def log_qa_turn(
        cls,
        session,
        *,
        conversation_id: str | None,
        user_message_id: str | None,
        assistant_message_id: str | None,
        kb_id: str | None,
        query: str,
        rewritten_query: str | None,
        answer: str,
        answer_type: str | None,
        sources: list
    ):
        """
        说明：log_qa_turn 函数，处理当前模块的对应业务步骤。
        """
        log = QaLog(
            id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            user_message_id=user_message_id,
            assistant_message_id=assistant_message_id,
            kb_id=kb_id,
            query=query,
            rewritten_query=rewritten_query,
            answer=answer,
            answer_type=answer_type,
            sources_json=json.dumps(sources or [], ensure_ascii=False),
            created_at=datetime.now()
        )
        session.add(log)
        session.commit()
        session.refresh(log)
        return log

    @classmethod
    def create_feedback(cls, message_id: str, req, session):
        """
        说明：create_feedback 函数，处理当前模块的对应业务步骤。
        """
        message = session.query(ConversationMessage).filter(ConversationMessage.id == message_id).first()
        if not message:
            raise HTTPException(status_code=404, detail="Message not found")
        if message.role != "assistant":
            raise HTTPException(status_code=400, detail="Only assistant messages can be rated")
        if req.rating not in {"helpful", "unhelpful"}:
            raise HTTPException(status_code=400, detail="rating must be helpful or unhelpful")

        feedback = MessageFeedback(
            id=str(uuid.uuid4()),
            message_id=message.id,
            conversation_id=message.conversation_id,
            rating=req.rating,
            comment=req.comment,
            created_at=datetime.now()
        )
        session.add(feedback)
        session.commit()
        session.refresh(feedback)

        return {
            "message_id": feedback.message_id,
            "conversation_id": feedback.conversation_id,
            "rating": feedback.rating,
            "comment": feedback.comment,
            "created_at": cls._format_dt(feedback.created_at)
        }

    @classmethod
    def get_metrics(cls, session):
        """
        说明：get_metrics 函数，处理当前模块的对应业务步骤。
        """
        total_qa = session.query(QaLog).count()
        helpful_count = session.query(MessageFeedback).filter(MessageFeedback.rating == "helpful").count()
        unhelpful_count = session.query(MessageFeedback).filter(MessageFeedback.rating == "unhelpful").count()
        feedback_count = helpful_count + unhelpful_count
        helpful_rate = helpful_count / feedback_count if feedback_count else 0
        answer_type_rows = (
            session.query(
                func.coalesce(QaLog.answer_type, "text").label("answer_type"),
                func.count(QaLog.id).label("count")
            )
            .group_by(func.coalesce(QaLog.answer_type, "text"))
            .all()
        )
        answer_type_feedback_rows = (
            session.query(
                func.coalesce(QaLog.answer_type, "text").label("answer_type"),
                func.count(QaLog.id).label("total_qa"),
                func.sum(
                    case((MessageFeedback.rating == "helpful", 1), else_=0)
                ).label("helpful_count"),
                func.sum(
                    case((MessageFeedback.rating == "unhelpful", 1), else_=0)
                ).label("unhelpful_count")
            )
            .outerjoin(MessageFeedback, MessageFeedback.message_id == QaLog.assistant_message_id)
            .group_by(func.coalesce(QaLog.answer_type, "text"))
            .all()
        )

        return {
            "total_qa": total_qa,
            "helpful_count": helpful_count,
            "unhelpful_count": unhelpful_count,
            "feedback_count": feedback_count,
            "helpful_rate": helpful_rate,
            "answer_type_catalog": cls.ANSWER_TYPE_CATALOG,
            "answer_type_breakdown": [
                {
                    "answer_type": row.answer_type,
                    "count": row.count
                }
                for row in answer_type_rows
            ],
            "answer_type_feedback_breakdown": [
                {
                    "answer_type": row.answer_type,
                    "total_qa": int(row.total_qa or 0),
                    "helpful_count": int(row.helpful_count or 0),
                    "unhelpful_count": int(row.unhelpful_count or 0),
                    "feedback_count": int(row.helpful_count or 0) + int(row.unhelpful_count or 0),
                    "helpful_rate": (
                        int(row.helpful_count or 0) / (int(row.helpful_count or 0) + int(row.unhelpful_count or 0))
                        if (int(row.helpful_count or 0) + int(row.unhelpful_count or 0))
                        else 0
                    )
                }
                for row in answer_type_feedback_rows
            ]
        }
