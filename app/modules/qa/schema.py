from pydantic import BaseModel
from typing import List, Optional


class QaRequest(BaseModel):
    """
    说明：QaRequest 类，封装当前模块的数据结构或业务逻辑。
    """
    query: str                                # 用户原始问题
    kb_id: Optional[str] = None               # 指定知识库 ID；为空时按启用知识库检索
    task_id: Optional[str] = None             # 指定文档任务 ID；用于限制只检索某个文档
    tone: Optional[str] = None                # 回答语气，如严谨、简洁、客服
    top_k: int = 5                            # 初始检索返回数量


class QaSource(BaseModel):
    """
    说明：QaSource 类，封装当前模块的数据结构或业务逻辑。
    """
    task_id: Optional[str] = None             # 来源文档任务 ID
    kb_id: Optional[str] = None               # 来源知识库 ID
    file_name: Optional[str] = None           # 来源文件名
    section: Optional[str] = None             # 来源 chunk 所属章节
    chunk_index: Optional[int] = None         # 来源 chunk 索引
    score: Optional[float] = None             # 检索综合得分
    snippet: str                              # 来源内容摘要片段


class QaAnswerPayload(BaseModel):
    """
    说明：QaAnswerPayload 类，封装当前模块的数据结构或业务逻辑。
    """
    applicable_stage: Optional[str] = None          # explanation：适用阶段
    calculation_steps: Optional[list[str]] = None   # explanation：计算步骤
    result_meaning: Optional[str] = None            # explanation：结果含义
    evidence: Optional[list[str]] = None            # explanation：原文依据
    detail_level: Optional[str] = None              # workflow_summary：摘要粒度
    input_sources: Optional[list[str]] = None       # workflow/domain：输入来源
    preprocessing: Optional[list[str]] = None       # workflow：数据整理与预处理
    main_conversion: Optional[list[str]] = None     # workflow：主体转换逻辑
    time_and_stage_calculation: Optional[list[str]] = None  # workflow：时间与阶段计算
    special_handling: Optional[list[str]] = None    # workflow：特殊处理
    supplemental_outputs: Optional[list[str]] = None  # workflow：补充输出
    final_outputs: Optional[list[str]] = None       # workflow：最终输出
    target_domain: Optional[str] = None             # domain_relation：目标域代码
    domain_role: Optional[str] = None               # domain/domain_relation：域角色定位
    direct_relations: Optional[list[str]] = None    # domain_relation：直接依赖关系
    design_relations: Optional[list[str]] = None    # domain_relation：设计层关系
    non_primary_relations: Optional[list[str]] = None  # domain_relation：非主要关系
    relation_conclusion: Optional[str] = None       # domain_relation：关系总结
    field_name: Optional[str] = None                # field_logic：目标字段名
    calculation_rules: Optional[list[str]] = None   # field_logic：字段计算/处理规则
    dependencies: Optional[list[str]] = None        # field_logic：依赖字段与前置条件
    special_cases: Optional[list[str]] = None       # field_logic：特殊情况
    related_outputs: Optional[list[str]] = None     # field_logic：相关输出字段
    diagram_type: Optional[str] = None              # diagram：图示类型，如 flow
    title: Optional[str] = None                     # diagram：图示标题
    source_answer_type: Optional[str] = None        # diagram：来源答案类型
    nodes: Optional[list[dict]] = None              # diagram：图节点列表
    edges: Optional[list[dict]] = None              # diagram：图连线列表


class QaResponse(BaseModel):
    """
    说明：QaResponse 类，封装当前模块的数据结构或业务逻辑。
    """
    query: str                                      # 用户原始问题
    rewritten_query: Optional[str] = None           # 检索前改写后的问题
    answer: str                                     # 最终渲染文本
    answer_type: str = "text"                       # 答案类型
    answer_payload: Optional[QaAnswerPayload] = None  # 结构化答案内容
    sources: List[QaSource]                         # 答案引用来源
    contexts: List[dict]                            # 后端实际使用的上下文


class ConversationCreate(BaseModel):
    """
    说明：ConversationCreate 类，封装当前模块的数据结构或业务逻辑。
    """
    title: Optional[str] = None                     # 会话标题
    kb_id: Optional[str] = None                     # 默认知识库 ID
    tone: Optional[str] = None                      # 默认回答语气


class ConversationResponse(BaseModel):
    """
    说明：ConversationResponse 类，封装当前模块的数据结构或业务逻辑。
    """
    id: str                                        # 会话 ID
    title: str                                     # 会话标题
    kb_id: Optional[str] = None                    # 会话绑定知识库 ID
    tone: Optional[str] = None                     # 会话回答语气
    created_at: str                                # 创建时间
    updated_at: str                                # 更新时间
    last_message: Optional[str] = None             # 最近一条消息摘要


class ConversationMessageCreate(BaseModel):
    """
    说明：ConversationMessageCreate 类，封装当前模块的数据结构或业务逻辑。
    """
    content: str                                   # 用户消息内容
    kb_id: Optional[str] = None                    # 本轮指定知识库 ID
    task_id: Optional[str] = None                  # 本轮指定文档任务 ID
    tone: Optional[str] = None                     # 本轮回答语气
    top_k: int = 5                                 # 本轮检索数量


class ConversationMessageResponse(BaseModel):
    """
    说明：ConversationMessageResponse 类，封装当前模块的数据结构或业务逻辑。
    """
    id: str                                        # 消息 ID
    role: str                                      # 消息角色：user / assistant
    content: str                                   # 消息文本内容
    answer_type: Optional[str] = None              # 助手答案类型
    answer_payload: Optional[QaAnswerPayload] = None  # 助手结构化答案
    sources: List[QaSource]                        # 助手答案引用来源
    created_at: str                                # 创建时间


class ConversationMessagesResponse(BaseModel):
    """
    说明：ConversationMessagesResponse 类，封装当前模块的数据结构或业务逻辑。
    """
    conversation_id: str                           # 会话 ID
    messages: List[ConversationMessageResponse]    # 会话消息列表


class ConversationTurnResponse(BaseModel):
    """
    说明：ConversationTurnResponse 类，封装当前模块的数据结构或业务逻辑。
    """
    conversation_id: str                           # 会话 ID
    rewritten_query: Optional[str] = None           # 本轮改写后的问题
    user_message: ConversationMessageResponse       # 用户消息
    assistant_message: ConversationMessageResponse  # 助手消息
