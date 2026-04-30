from typing import List, Optional

from pydantic import BaseModel


class KnowledgeCard(BaseModel):
    """
    说明：KnowledgeCard 类，封装当前模块的数据结构或业务逻辑。
    """
    title: str                              # 标题
    category: str                           # 分类
    summary: str                            # 摘要
    details: List[str] = []                 # 详情


class KnowledgeCardResponse(BaseModel):
    """
    说明：KnowledgeCardResponse 类，封装当前模块的数据结构或业务逻辑。
    """
    task_id: str                            # 任务ID
    file_name: str                          # 文件名
    status: str                             # 状态
    cards: List[KnowledgeCard] = []         # 卡片
    error_message: Optional[str] = None     # 错误信息
    created_at: str                         # 创建时间
    updated_at: str                         # 更新时间
