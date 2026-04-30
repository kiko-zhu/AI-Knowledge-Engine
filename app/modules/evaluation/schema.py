from typing import Optional

from pydantic import BaseModel


class FeedbackCreate(BaseModel):
    """
        提交回答反馈”接口的请求体模型"
    """
    rating: str                             #  helpful / unhelpful
    comment: Optional[str] = None           # 评论


class FeedbackResponse(BaseModel):
    """
    说明：FeedbackResponse 类，封装当前模块的数据结构或业务逻辑。
    """
    message_id: str                         # 消息_id
    conversation_id: Optional[str] = None   # 对话_id
    rating: str                             #  helpful / unhelpful
    comment: Optional[str] = None           # 评论
    created_at: str                         # 创建时间


class EvaluationMetricsResponse(BaseModel):
    """
    说明：EvaluationMetricsResponse 类，封装当前模块的数据结构或业务逻辑。
    """
    total_qa: int                           # 问答总数
    helpful_count: int                      # 有帮助的回答数
    unhelpful_count: int                    # 无帮助的回答数
    feedback_count: int                     # 反馈总数
    helpful_rate: float                     # 有帮助的回答率
    answer_type_catalog: list[dict]         # 回答类型目录
    answer_type_breakdown: list[dict]       # 回答类型分布
    answer_type_feedback_breakdown: list[dict]  # 回答类型反馈分布
