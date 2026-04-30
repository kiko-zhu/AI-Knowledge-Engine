from typing import List, Optional

from pydantic import BaseModel


class SummarySection(BaseModel):
    """
    说明：SummarySection 类，封装当前模块的数据结构或业务逻辑。
    """
    title: str                              # 摘要章节标题
    desc: str                               # 摘要章节说明


class SummaryResponse(BaseModel):
    """
    说明：SummaryResponse 类，封装当前模块的数据结构或业务逻辑。
    """
    task_id: str                            # 文档任务 ID
    file_name: str                          # 文件名
    status: str                             # 摘要生成状态
    summary: Optional[str] = None           # 文档摘要文本
    keywords: List[str] = []                # 关键词列表
    sections: List[SummarySection] = []     # 章节摘要列表
    error_message: Optional[str] = None     # 摘要生成错误信息
    created_at: str                         # 创建时间
    updated_at: str                         # 更新时间
