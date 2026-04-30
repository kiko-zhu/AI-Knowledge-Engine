# app/modules/search/schema.py
from pydantic import BaseModel
from typing import Optional, List

class SearchRequest(BaseModel):
    """
    说明：SearchRequest 类，封装当前模块的数据结构或业务逻辑。
    """
    query: str                          # 搜索内容
    kb_id: Optional[str] = None         # 知识库ID
    top_k: int = 5                      # 返回结果数量

class SearchItem(BaseModel):
    """
    说明：SearchItem 类，封装当前模块的数据结构或业务逻辑。
    """
    score: float                        # 得分
    content: str                        # 内容
    chunk_index: int                    # 块索引
    file_name: Optional[str]            # 文件名
    kb_id: Optional[str]                # 知识库ID
    section: Optional[str]              # 章节

class SearchResponse(BaseModel):
    """
    说明：SearchResponse 类，封装当前模块的数据结构或业务逻辑。
    """
    query: str                          # 搜索内容
    top_k: int                          # 返回结果数量
    items: List[SearchItem]             # 搜索结果