import json
import re
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import text

from app.core.llm import chat
from app.modules.qa.field_logic import build_field_logic_payload_from_contexts
from app.modules.qa.field_logic import has_substantive_field_logic
from app.modules.qa.field_logic import normalize_field_logic_payload
from app.modules.qa.intent import CODE_TOKEN_RE
from app.modules.qa.intent import extract_field_tokens as extract_query_field_tokens
from app.modules.qa.intent import extract_target_domain_code as extract_query_domain_code
from app.modules.evaluation.service import EvaluationService
from app.modules.qa.model import Conversation, ConversationMessage
from app.modules.search.service import SearchService
from app.modules.task.model import DocumentChunk, KnowledgeBase, Task


class QaService:
    """
    说明：QaService 类，封装当前模块的数据结构或业务逻辑。
    """
    MAX_CONTEXTS = 3
    MAX_CONTEXT_CHARS = 3200
    NEIGHBOR_WINDOW = 1
    HISTORY_WINDOW = 6
    FILE_SPEC_FLAGS = ["文件路径", "路径", "文件格式", "格式", "输出文件"]
    EXPLANATION_FLAGS = ["解释", "中文说", "中文解释", "用中文", "说一下", "讲一下", "逻辑", "怎么计算", "怎么算", "含义"]
    TEACHING_FLAGS = ["更能理解", "更好理解", "更容易理解", "更容易懂", "通俗", "讲给别人", "怎么讲", "换种说法", "更好解释", "让别人理解", "怎么让别人"]
    VISUALIZATION_FLAGS = ["画图", "图示", "流程图", "图解", "可视化", "画一下", "画出来", "图形"]
    WORKFLOW_FLAGS = ["整个流程", "整体流程", "完整流程", "流程是怎么样", "流程是什么", "从输入到输出", "用自己的话概括", "整体过程", "全流程"]
    DETAILED_FLAGS = ["详细说明", "详细讲", "展开说", "展开讲", "具体讲讲", "具体说明", "详细一点", "说详细点", "细讲", "详细描述"]
    DOMAIN_RELATION_FLAGS = ["什么关系", "有什么关系", "之间有什么联系", "之间的联系", "与其他域", "和其他域", "依赖哪些域", "被哪些域依赖", "和哪些域有关", "有什么联系"]
    DOMAIN_LOGIC_FLAGS = ["逻辑是什么", "主要逻辑", "核心逻辑", "转换逻辑", "是做什么的", "主要做什么"]
    FIELD_LOGIC_FLAGS = ["怎么计算", "如何计算", "怎么算", "如何处理", "怎么处理", "怎么生成", "如何生成", "计算逻辑", "处理逻辑", "生成逻辑", "来源逻辑", "是什么", "代表什么", "含义是什么"]
    CODE_TOKEN_RE = CODE_TOKEN_RE

    @classmethod
    def ensure_schema(cls, engine):
        """
        为旧库补齐问答消息表新增字段。
        正式项目里答案协议一旦升级，历史会话也要能承载新字段，不能只靠内存临时返回。
        """
        with engine.begin() as conn:
            columns = [row[1] for row in conn.execute(text("PRAGMA table_info(conversation_messages)")).fetchall()]
            if "answer_type" not in columns:
                conn.execute(text("ALTER TABLE conversation_messages ADD COLUMN answer_type VARCHAR"))
            if "answer_payload" not in columns:
                conn.execute(text("ALTER TABLE conversation_messages ADD COLUMN answer_payload TEXT"))

    @classmethod
    def _format_dt(cls, value: datetime | None) -> str:
        """
        说明：_format_dt 函数，处理当前模块的对应业务步骤。
        """
        if not value:
            return ""
        return value.isoformat(timespec="seconds")

    @classmethod
    def is_listing_query(cls, query: str) -> bool:
        """
        说明：is_listing_query 函数，处理当前模块的对应业务步骤。
        """
        flags = ["哪些", "有哪些", "包含", "包括", "列出", "分别是什么", "有哪几"]
        return any(flag in query for flag in flags)

    @classmethod
    def is_file_spec_query(cls, query: str) -> bool:
        """
        判断问题是否在询问文档输出文件相关的半结构化属性。
        这类问题更适合先做规则抽取，再决定是否回退给模型。
        """
        value = (query or "").strip()
        return any(flag in value for flag in cls.FILE_SPEC_FLAGS)

    @classmethod
    def is_explanation_query(cls, query: str) -> bool:
        """
        判断问题是否属于“解释逻辑 / 中文说明”类型。
        这类问题需要把原始公式翻译成中文步骤，而不是直接复制代码。
        """
        value = (query or "").strip()
        return any(flag in value for flag in cls.EXPLANATION_FLAGS)

    @classmethod
    def is_teaching_query(cls, query: str) -> bool:
        """
        判断问题是否在要求“换一种更容易理解的表达方式”。
        这类问题不是单纯追问事实，而是在前一轮事实基础上做表达优化。
        """
        value = (query or "").strip()
        return any(flag in value for flag in cls.TEACHING_FLAGS)

    @classmethod
    def is_visualization_query(cls, query: str) -> bool:
        """
        判断用户是否要求把上一轮事实答案换成图示表达。
        这类追问不应重新检索事实，否则容易被相似域的 chunk 带偏。
        """
        value = (query or "").strip()
        return any(flag in value for flag in cls.VISUALIZATION_FLAGS)

    @classmethod
    def is_workflow_query(cls, query: str) -> bool:
        """
        判断问题是否在询问“整个流程 / 完整流程 / 从输入到输出”。
        这类问题属于流程总结，不应该再落到局部逻辑解释链路里。
        """
        value = (query or "").strip()
        return any(flag in value for flag in cls.WORKFLOW_FLAGS)

    @classmethod
    def is_domain_relation_query(cls, query: str) -> bool:
        """
        判断问题是否在询问“某个域与其他域的关系”。
        这类问题不能只看单个域文档，还要反向找哪些域引用了该域。
        """
        value = (query or "").strip().upper()
        return "域" in value and any(flag in value for flag in cls.DOMAIN_RELATION_FLAGS)

    @classmethod
    def is_domain_logic_query(cls, query: str) -> bool:
        """
        判断问题是否在询问某个域本身的主逻辑。
        这类问题不是单个字段解释，也不是全流程总结，而是“某域主要怎么转换”的域级概览。
        """
        value = (query or "").strip()
        return bool(cls.extract_target_domain_code(value)) and any(flag in value for flag in cls.DOMAIN_LOGIC_FLAGS)

    @classmethod
    def classify_query_intent(cls, query: str) -> str:
        """
        统一的问句意图分类入口。
        正式环境里，问答路由要先分清问题类型，再决定检索和生成策略，避免各种规则互相污染。
        """
        if cls.is_field_logic_query(query):     # 字段逻辑
            return "field_logic"
        if cls.is_domain_relation_query(query): # 域关系
            return "domain_relation"
        if cls.is_workflow_query(query):        # 流程总结
            return "workflow_summary"
        if cls.is_domain_logic_query(query):    # 域逻辑
            return "domain_logic"
        if cls.is_file_spec_query(query):       # 文档输出文件
            return "file_spec"
        if cls.is_explanation_query(query):     # 中文说明
            return "explanation"
        if cls.is_listing_query(query):         # 列表
            return "list"
        return "text"

    @classmethod
    def is_field_logic_query(cls, query: str) -> bool:
        """
        判断问题是否在询问“某域某字段怎么计算/怎么处理”。
        这类问题必须锁定目标域和字段本身，不能让通用检索被其他文档中的相似 FAQ 带偏。
        """
        value = (query or "").strip()
        return bool(cls.extract_target_domain_code(value)) and bool(cls.extract_field_tokens(value)) and any(
            flag in value for flag in cls.FIELD_LOGIC_FLAGS
        )

    @classmethod
    def extract_target_domain_code(cls, query: str) -> str | None:
        """
        从问题里提取目标域代码。
        当前优先支持 SEND 常见的两位大写域代码问法，例如 EX域、BW域、DM域。
        """
        return extract_query_domain_code(query)

    @classmethod
    def get_workflow_detail_level(cls, query: str) -> str:
        """
        判断流程总结应该输出简版还是详版。
        正式项目里“整个流程”和“详细说明流程”不能共用同一份摘要粒度。
        """
        value = (query or "").strip()
        return "detailed" if any(flag in value for flag in cls.DETAILED_FLAGS) else "summary"

    @classmethod
    def extract_field_tokens(cls, query: str) -> list[str]:
        """
        提取问题里的显式字段/代码标识符。
        正式环境里，像 VSTPT / EXSTDTC 这类字段名一旦出现在原问题里，就必须在改写后保留，
        否则检索会被历史上下文带偏。
        """
        return extract_query_field_tokens(query)

    @classmethod
    def should_rewrite_query(cls, query: str, history_messages: list | None = None) -> bool:
        """
        说明：should_rewrite_query 函数，处理当前模块的对应业务步骤。
        """
        if not history_messages:
            return False

        value = (query or "").strip()
        if not value:
            return False

        # 原问题已经明确包含目标域和字段/指标时，说明检索目标足够具体，
        # 这类问题继续改写的收益很低，反而容易被上一轮上下文污染。
        has_domain = bool(cls.extract_target_domain_code(value))
        has_field_tokens = bool(cls.extract_field_tokens(value))
        if has_domain and has_field_tokens:
            return False

        follow_up_flags = [
            "它", "这个", "那个", "这些", "那些", "上一条", "上一个", "上面", "前面",
            "继续", "然后", "再说", "第3", "第三", "第4", "第四", "第5", "第五",
            "区别", "为什么", "怎么", "如何", "展开", "详细说", "进一步"
        ]

        if len(value) <= 18:
            return True

        return any(flag in value for flag in follow_up_flags)

    @classmethod
    def build_conversation_title(cls, text: str) -> str:
        """
        说明：build_conversation_title 函数，处理当前模块的对应业务步骤。
        """
        value = (text or "").strip()
        if not value:
            return "新会话"
        return value[:24]

    @classmethod
    def get_conversation_or_404(cls, conversation_id: str, session):
        """
        说明：get_conversation_or_404 函数，处理当前模块的对应业务步骤。
        """
        conversation = session.query(Conversation).filter(Conversation.id == conversation_id).first()
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return conversation

    @classmethod
    def merge_adjacent_contexts(cls, items: list):
        """
        说明：merge_adjacent_contexts 函数，处理当前模块的对应业务步骤。
        """
        if not items:
            return []

        merged = []

        for item in sorted(items, key=lambda value: (-float(value.get("score", 0)), value.get("chunk_index", 0))):
            content = (item.get("content") or "").strip()
            if not content:
                continue

            appended = False

            for existing in merged:
                same_task = existing.get("task_id") == item.get("task_id")
                same_section = (existing.get("section") or "") == (item.get("section") or "")
                index_gap = abs(int(existing.get("chunk_index", 0)) - int(item.get("chunk_index", 0)))

                if same_task and same_section and index_gap <= 1:
                    existing_content = (existing.get("content") or "").strip()
                    if content not in existing_content:
                        if int(item.get("chunk_index", 0)) < int(existing.get("chunk_index", 0)):
                            existing["content"] = f"{content}\n\n{existing_content}"
                            existing["chunk_index"] = item.get("chunk_index", existing.get("chunk_index"))
                        else:
                            existing["content"] = f"{existing_content}\n\n{content}"
                        existing["score"] = max(float(existing.get("score", 0)), float(item.get("score", 0)))
                    appended = True
                    break

            if not appended:
                merged.append(dict(item))

        return merged

    @classmethod
    def expand_with_neighbors(cls, items: list, session):
        """
        说明：expand_with_neighbors 函数，处理当前模块的对应业务步骤。
        """
        expanded = []
        seen = set()

        for item in items:
            task_id = item.get("task_id")
            chunk_index = item.get("chunk_index")

            if task_id is None or chunk_index is None:
                key = (item.get("task_id"), item.get("chunk_index"), item.get("content"))
                if key not in seen:
                    expanded.append(item)
                    seen.add(key)
                continue

            neighbor_indexes = range(int(chunk_index) - cls.NEIGHBOR_WINDOW, int(chunk_index) + cls.NEIGHBOR_WINDOW + 1)
            rows = session.query(DocumentChunk) \
                .filter(
                    DocumentChunk.task_id == task_id,
                    DocumentChunk.chunk_index.in_(list(neighbor_indexes))
                ) \
                .order_by(DocumentChunk.chunk_index.asc()) \
                .all()

            base_score = float(item.get("score", 0))

            for row in rows:
                key = (row.task_id, row.chunk_index, row.content)
                if key in seen:
                    continue

                expanded.append({
                    "score": base_score if row.chunk_index == chunk_index else max(base_score - 0.03, 0),
                    "content": row.content,
                    "chunk_index": row.chunk_index,
                    "task_id": row.task_id,
                    "file_name": item.get("file_name"),
                    "kb_id": item.get("kb_id"),
                    "section": SearchService.extract_section(row.content),
                    "title_path": SearchService.extract_title_path(row.content)
                })
                seen.add(key)

        return expanded or items

    @classmethod
    def select_contexts(cls, items: list, session):
        """
        说明：select_contexts 函数，处理当前模块的对应业务步骤。
        """
        expanded_items = cls.expand_with_neighbors(items, session)
        merged_items = cls.merge_adjacent_contexts(expanded_items)
        selected = []
        seen_contents = set()
        current_chars = 0

        for item in merged_items:
            content = (item.get("content") or "").strip()
            if not content or content in seen_contents:
                continue

            next_total = current_chars + len(content)
            if selected and next_total > cls.MAX_CONTEXT_CHARS:
                break

            selected.append(item)
            seen_contents.add(content)
            current_chars = next_total

            if len(selected) >= cls.MAX_CONTEXTS:
                break

        return selected or merged_items[:1] or items[:1]

    @classmethod
    def clean_source_text(cls, content: str) -> str:
        """
        说明：clean_source_text 函数，处理当前模块的对应业务步骤。
        """
        raw = (content or "").strip()
        marker = "标题路径:"
        marker_index = raw.rfind(marker)

        if marker_index != -1:
            structured = raw[marker_index:].strip()
            lines = structured.splitlines()
            body = "\n".join(lines[1:]).strip()
            return body or structured

        return raw

    @classmethod
    def build_sources(cls, contexts: list):
        """
        说明：build_sources 函数，处理当前模块的对应业务步骤。
        """
        sources = []

        for context in contexts:
            cleaned = cls.clean_source_text(context.get("content") or "")
            snippet = cleaned[:280].strip()
            if len(cleaned) > 280:
                snippet = f"{snippet}..."

            sources.append({
                "task_id": context.get("task_id"),
                "kb_id": context.get("kb_id"),
                "file_name": context.get("file_name"),
                "section": context.get("section"),
                "chunk_index": context.get("chunk_index"),
                "score": float(context.get("score", 0)) if context.get("score") is not None else None,
                "snippet": snippet or "-"
            })

        return sources

    @classmethod
    def extract_requested_file_fields(cls, query: str):
        """
        根据问题内容识别用户到底在问哪些字段。
        当前优先覆盖“文件路径 / 文件格式”这两类在转换说明里高频出现的结构化字段
        """
        requested = []
        value = (query or "").strip()

        if "文件路径" in value or ("路径" in value and "代码路径" not in value):
            requested.append("file_path")

        if "文件格式" in value or "格式" in value:
            requested.append("file_format")

        return requested

    @classmethod
    def pick_relevant_file_spec_contexts(cls, query: str, contexts: list):
        """
        从候选上下文中挑出与“文件路径 / 文件格式”最相关的 chunk。
        优先看 section 和 title_path，再回退到正文命中。
        """
        requested = cls.extract_requested_file_fields(query)
        if not requested:
            return []

        selected = []
        for context in contexts:
            section = (context.get("section") or "").strip()
            title_path = (context.get("title_path") or "").strip()
            content = cls.clean_source_text(context.get("content") or "")
            haystack = "\n".join([section, title_path, content])

            matched = False
            if "file_path" in requested and "文件路径" in haystack:
                matched = True
            if "file_format" in requested and "文件格式" in haystack:
                matched = True
            if "输出文件" in haystack:
                matched = True

            if matched:
                selected.append(context)

        return selected

    @classmethod
    def extract_path_lines(cls, content: str):
        """
        从 chunk 正文中提取路径型输出。
        这类行通常出现在代码块中，并带有 .xpt 等输出文件后缀。
        """
        lines = []
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or line.startswith("```"):
                continue

            if "/" in line and re.search(r"\.(xpt|csv|xlsx|txt)\b", line, flags=re.IGNORECASE):
                lines.append(line)
                continue

            if "\\" in line and re.search(r"\.(xpt|csv|xlsx|txt)\b", line, flags=re.IGNORECASE):
                lines.append(line)

        return lines

    @classmethod
    def extract_format_lines(cls, content: str):
        """
        从 chunk 正文中提取格式描述。
        跳过标题和代码围栏，只保留真正的说明文本。
        """
        lines = []
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or line.startswith("```"):
                continue

            if "文件格式" in line and len(line) <= 20:
                continue

            lines.append(line)

        return lines

    @classmethod
    def query_mentions_file(cls, query: str, file_names: list[str]):
        """
        判断用户问题里是否已经明确提到某个文件。
        如果没有明确文件名，而检索结果跨多个文档，就不应该默认猜一个。
        """
        query_text = (query or "").lower()
        for file_name in file_names:
            if file_name and file_name.lower() in query_text:
                return True
        return False

    @classmethod
    def build_file_spec_answer(cls, query: str, contexts: list, task_id: str = None):
        """
        针对“文件路径 / 文件格式”这类字段型问题构造稳定答案。
        正式项目里，这类半结构化信息优先走规则抽取，而不是完全依赖大模型自由生成。
        """
        relevant_contexts = cls.pick_relevant_file_spec_contexts(query, contexts)
        if not relevant_contexts:
            return None

        requested = cls.extract_requested_file_fields(query)
        grouped = {}
        for context in relevant_contexts:
            file_name = context.get("file_name") or "未知文件"
            bucket = grouped.setdefault(file_name, {
                "file_name": file_name,
                "paths": [],
                "formats": []
            })

            cleaned = cls.clean_source_text(context.get("content") or "")
            if "file_path" in requested and "文件路径" in "\n".join([
                context.get("section") or "",
                context.get("title_path") or "",
                cleaned
            ]):
                for item in cls.extract_path_lines(cleaned):
                    if item not in bucket["paths"]:
                        bucket["paths"].append(item)

            if "file_format" in requested and "文件格式" in "\n".join([
                context.get("section") or "",
                context.get("title_path") or "",
                cleaned
            ]):
                for item in cls.extract_format_lines(cleaned):
                    if item not in bucket["formats"]:
                        bucket["formats"].append(item)

        groups = [item for item in grouped.values() if item["paths"] or item["formats"]]
        if not groups:
            return None

        matched_file_group = next(
            (item for item in groups if item["file_name"] and item["file_name"].lower() in (query or "").lower()),
            None
        )

        if len(groups) > 1 and not task_id and not matched_file_group:
            file_names = "、".join(item["file_name"] for item in groups[:5])
            return (
                f"当前知识库中有多个文档都命中了“{query}”相关内容，至少包括：{file_names}。"
                "如果你要单个文档的确定答案，请在问题里明确文件名，或在文档范围内提问。"
            )

        target = matched_file_group or groups[0]
        lines = [f"根据检索片段，{target['file_name']} 的输出文件信息如下：", ""]

        if "file_path" in requested and target["paths"]:
            lines.append("- 文件路径：")
            for item in target["paths"]:
                lines.append(f"  - `{item}`")
            lines.append("")

        if "file_format" in requested and target["formats"]:
            lines.append("- 文件格式：")
            for item in target["formats"]:
                lines.append(f"  - {item}")
            lines.append("")

        return "\n".join(lines).strip()

    @classmethod
    def render_history(cls, history_messages: list):
        """
        说明：render_history 函数，处理当前模块的对应业务步骤。
        """
        rendered = []
        for message in history_messages[-cls.HISTORY_WINDOW:]:
            role = "用户" if message.role == "user" else "助手"
            rendered.append(f"{role}: {message.content}")
        return "\n".join(rendered)

    @classmethod
    def extract_top_level_numbered_items(cls, contexts: list):
        """
        提取片段里的一级编号项，给模型一个显式结构约束。
        这样回答“有哪些”时，模型更不容易把二级 bullet 误编号成一级条目。
        """
        items = []
        seen_numbers = set()

        for context in contexts:
            content = cls.clean_source_text(context.get("content") or "")
            for line in content.splitlines():
                stripped = line.strip()
                match = re.match(r"^(\d+)\.\s*(.+)$", stripped)
                if not match:
                    continue

                number = match.group(1)
                if number in seen_numbers:
                    continue

                seen_numbers.add(number)
                items.append(f"{number}. {match.group(2).strip()}")

        return items

    @classmethod
    def extract_numbered_blocks(cls, contexts: list):
        """
        从同一章节的片段里提取完整的一级编号块。
        对“有哪些”类问题，优先直接使用这些结构化块组装答案，
        比完全交给 LLM 自由生成更稳。
        """
        if not contexts:
            return []

        primary_section = contexts[0].get("section")
        merged_lines = []

        for context in contexts:
            if primary_section and context.get("section") != primary_section:
                continue

            content = cls.clean_source_text(context.get("content") or "")
            merged_lines.extend(content.splitlines())

        blocks = []
        current_number = None
        current_lines = []
        seen_numbers = set()

        def flush():
            """
            说明：flush 函数，处理当前模块的对应业务步骤。
            """
            nonlocal current_number, current_lines
            if current_number and current_lines:
                text = "\n".join(line.rstrip() for line in current_lines).strip()
                if text:
                    blocks.append((current_number, text))
            current_number = None
            current_lines = []

        for raw_line in merged_lines:
            line = raw_line.rstrip()
            stripped = line.strip()

            if not stripped:
                if current_number:
                    current_lines.append("")
                continue

            if stripped.startswith("#"):
                flush()
                continue

            match = re.match(r"^(\d+)\.\s*(.+)$", stripped)
            if match:
                number = match.group(1)
                if number in seen_numbers:
                    flush()
                    current_number = number
                    current_lines = [f"{number}. {match.group(2).strip()}"]
                    continue

                flush()
                current_number = number
                current_lines = [f"{number}. {match.group(2).strip()}"]
                seen_numbers.add(number)
                continue

            if current_number:
                current_lines.append(stripped)

        flush()
        return blocks

    @classmethod
    def build_structured_list_answer(cls, contexts: list):
        """
        说明：build_structured_list_answer 函数，处理当前模块的对应业务步骤。
        """
        blocks = cls.extract_numbered_blocks(contexts)
        if not blocks:
            return None

        lines = ["根据提供的检索片段，关键逻辑包括：", ""]
        for number, block in blocks:
            lines.append(block)
            lines.append("")

        return "\n".join(lines).strip()

    @classmethod
    def build_explanation_context_text(cls, contexts: list):
        """
        将解释型问答涉及的上下文整理成紧凑文本，供结构化抽取使用。
        这里保留文件名、章节和正文，便于模型按“阶段 / 步骤 / 含义 / 依据”提炼。
        """
        rendered = []
        for idx, context in enumerate(contexts, start=1):
            rendered.append(
                f"【片段{idx}】\n"
                f"文件: {context.get('file_name') or '-'}\n"
                f"章节: {context.get('section') or '-'}\n"
                f"内容:\n{cls.clean_source_text(context.get('content') or '')}"
            )
        return "\n\n".join(rendered)

    @classmethod
    def build_domain_relation_patterns(cls, domain_code: str):
        """
        为域关系问题构造反向引用检索模式。
        正式项目里，像“EX 域和其他域的关系”这类问题，关键证据通常在别的域文档里。
        """
        if not domain_code:
            return []

        upper = domain_code.upper()
        lower = upper.lower()
        patterns = [
            f"{upper}域",
            f"{upper} 域",
            f"依赖{upper}",
            f"依赖 {upper}",
            f"{lower}.xpt",
            f"{upper}STDTC",
            f"{upper}ENDTC",
            f"{upper}STDY",
            f"{upper}RPSTDY",
            f"读取已生成的 `{lower}.xpt`",
            f"必须先生成 {upper} 域",
            f"必须先生成{upper}域",
        ]
        seen = []
        for item in patterns:
            if item not in seen:
                seen.append(item)
        return seen

    @classmethod
    def fetch_domain_relation_candidates(
        cls,
        domain_code: str,
        session,
        kb_id: str = None,
        task_id: str = None
    ):
        """
        在检索结果之外追加“反向引用”候选片段。
        这一步的目标不是取相似度最高，而是尽量找出哪些域明确写了“依赖 EX / 读取 ex.xpt / 使用 EXSTDTC”。
        """
        if not domain_code:
            return []

        patterns = cls.build_domain_relation_patterns(domain_code)
        q = session.query(DocumentChunk, Task).join(Task, DocumentChunk.task_id == Task.id)
        if task_id:
            q = q.join(KnowledgeBase, KnowledgeBase.id == Task.knowledge_base_id).filter(
                Task.id == task_id,
                KnowledgeBase.enabled.is_(True)
            )
        elif kb_id:
            q = q.join(KnowledgeBase, KnowledgeBase.id == Task.knowledge_base_id).filter(
                Task.knowledge_base_id == kb_id,
                KnowledgeBase.enabled.is_(True)
            )
        else:
            q = q.join(KnowledgeBase, KnowledgeBase.id == Task.knowledge_base_id).filter(KnowledgeBase.enabled.is_(True))

        candidates = []
        target_file = f"{domain_code.upper()}.md"
        for chunk, task in q.all():
            content = chunk.content or ""
            file_name = task.file_name if task else None
            section = SearchService.extract_section(content)
            title_path = SearchService.extract_title_path(content)
            haystack = "\n".join([
                (file_name or ""),
                section or "",
                title_path or "",
                cls.clean_source_text(content)
            ])

            pattern_hits = [item for item in patterns if item and item in haystack]
            if not pattern_hits and (file_name or "").upper() != target_file.upper():
                continue

            score = 0.0
            if (file_name or "").upper() == target_file.upper():
                score += 1.25
            if "依赖" in haystack and domain_code.upper() in haystack.upper():
                score += 1.1
            if f"{domain_code.lower()}.xpt" in haystack.lower():
                score += 1.0
            if f"{domain_code.upper()}STDTC" in haystack.upper() or f"{domain_code.upper()}ENDTC" in haystack.upper():
                score += 0.9
            if "Q1: 为什么" in haystack and "依赖" in haystack:
                score += 0.8
            score += min(len(pattern_hits) * 0.12, 0.6)

            candidates.append({
                "score": score,
                "content": content,
                "chunk_index": chunk.chunk_index,
                "task_id": chunk.task_id,
                "file_name": file_name,
                "kb_id": task.knowledge_base_id if task else None,
                "section": section,
                "title_path": title_path
            })

        return sorted(candidates, key=lambda value: value["score"], reverse=True)[:18]

    @classmethod
    def select_workflow_contexts(cls, items: list, session):
        """
        为流程型问题挑选“全流程主干”片段。
        正式项目里流程总结不能只拿相似度最高的局部 chunk，还要优先覆盖输入、主转换、补充处理和输出。
        """
        expanded_items = cls.expand_with_neighbors(items, session)
        merged_items = cls.merge_adjacent_contexts(expanded_items)

        def score_context(item: dict) -> int:
            """
            说明：score_context 函数，处理当前模块的对应业务步骤。
            """
            section = (item.get("section") or "").lower()
            title_path = (item.get("title_path") or "").lower()
            text = f"{section} {title_path}"
            score = 0
            if "数据来源" in text or "输入" in text:
                score += 8
            if "主转换流程" in text or "bw_csv" in text:
                score += 8
            if "总控" in text or "convert_" in text:
                score += 7
            if "输出文件" in text or "输出" in text:
                score += 6
            if "数据流转图" in text:
                score += 6
            if "关键辅助函数" in text:
                score += 5
            if "补充" in text or "supp" in text:
                score += 4
            if "阶段" in text:
                score += 2
            return score

        selected = []
        covered_sections = set()
        current_chars = 0

        for item in sorted(
            merged_items,
            key=lambda value: (score_context(value), float(value.get("score", 0))),
            reverse=True
        ):
            content = (item.get("content") or "").strip()
            if not content:
                continue

            section_key = ((item.get("section") or "") + "|" + (item.get("title_path") or "")).strip()
            if section_key and section_key in covered_sections and len(selected) >= 4:
                continue

            next_total = current_chars + len(content)
            if selected and next_total > cls.MAX_CONTEXT_CHARS + 1200:
                break

            selected.append(item)
            current_chars = next_total
            if section_key:
                covered_sections.add(section_key)

            if len(selected) >= 6:
                break

        return selected or cls.select_contexts(items, session)

    @classmethod
    def select_domain_relation_contexts(
        cls,
        query: str,
        items: list,
        session,
        kb_id: str = None,
        task_id: str = None
        ):
        """
        为“某个域和其他域的关系”挑选证据片段。
        关键是把目标域自身说明 + 其他域对它的反向引用一起带进上下文，避免只答成局部关系。
        """
        domain_code = cls.extract_target_domain_code(query)
        expanded_items = cls.expand_with_neighbors(items, session)
        reverse_candidates = cls.fetch_domain_relation_candidates(domain_code, session, kb_id=kb_id, task_id=task_id)
        merged_items = cls.merge_adjacent_contexts(expanded_items + reverse_candidates)
        target_file = f"{(domain_code or '').upper()}.md"

        def score_context(item: dict) -> float:
            """
            说明：score_context 函数，处理当前模块的对应业务步骤。
            """
            file_name = (item.get("file_name") or "").upper()
            section = (item.get("section") or "").lower()
            title_path = (item.get("title_path") or "").lower()
            content = cls.clean_source_text(item.get("content") or "")
            haystack = f"{file_name}\n{section}\n{title_path}\n{content}"
            score = float(item.get("score", 0))

            if target_file and file_name == target_file.upper():
                score += 2.2
            if "数据来源与输入" in haystack or "常见问题" in haystack or "数据流转图" in haystack:
                score += 0.7
            if "依赖" in haystack and (domain_code or "") in haystack.upper():
                score += 1.6
            if domain_code and f"{domain_code.lower()}.xpt" in haystack.lower():
                score += 1.4
            if domain_code and (
                f"{domain_code.upper()}STDTC" in haystack.upper()
                or f"{domain_code.upper()}ENDTC" in haystack.upper()
                or f"{domain_code.upper()}STDY" in haystack.upper()
            ):
                score += 1.2
            if "计划" in haystack or "设计" in haystack or "执行" in haystack:
                score += 0.5
            if "relrec" in haystack:
                score -= 0.2
            return score

        ranked_items = sorted(merged_items, key=score_context, reverse=True)
        selected = []
        covered_files = set()
        current_chars = 0

        target_item = None
        reverse_file_best = {}
        for item in ranked_items:
            file_key = (item.get("file_name") or "").upper()
            file_domain = cls.extract_domain_code_from_file(item.get("file_name") or "")
            if target_file and file_key == target_file.upper() and target_item is None:
                target_item = item
            if file_domain and domain_code and file_domain != domain_code.upper() and file_domain not in reverse_file_best:
                reverse_file_best[file_domain] = item

        preferred_domain_order = ["DM", "BW", "BG", "VS", "CL", "RE"]
        preferred_items = []
        if target_item:
            preferred_items.append(target_item)
        for file_domain in preferred_domain_order:
            if file_domain in reverse_file_best:
                preferred_items.append(reverse_file_best[file_domain])
        for file_domain, item in reverse_file_best.items():
            if file_domain not in preferred_domain_order:
                preferred_items.append(item)

        ordered_items = preferred_items + [
            item for item in ranked_items
            if item not in preferred_items
        ]

        for item in ordered_items:
            content = (item.get("content") or "").strip()
            if not content:
                continue

            file_key = (item.get("file_name") or "").upper()
            next_total = current_chars + len(content)
            if selected and next_total > cls.MAX_CONTEXT_CHARS + 1800:
                break

            if file_key and file_key in covered_files and len(selected) >= 5:
                continue

            selected.append(item)
            current_chars = next_total
            if file_key:
                covered_files.add(file_key)

            if len(selected) >= 8:
                break

        return selected or cls.select_contexts(items, session)

    @classmethod
    def select_domain_logic_contexts(
        cls,
        query: str,
        items: list,
        session,
        kb_id: str = None,
        task_id: str = None
    ):
        """
        为“某个域的逻辑是什么”选择域级概览上下文。
        这类问题应优先覆盖目标域自己的输入、关键逻辑、时间处理、输出，而不是跨域散点。
        """
        domain_code = cls.extract_target_domain_code(query)
        if not domain_code:
            return cls.select_contexts(items, session)

        target_file = f"{domain_code.upper()}.md"
        expanded_items = cls.expand_with_neighbors(items, session)

        q = session.query(DocumentChunk, Task).join(Task, DocumentChunk.task_id == Task.id)
        if task_id:
            q = q.join(KnowledgeBase, KnowledgeBase.id == Task.knowledge_base_id).filter(
                Task.id == task_id,
                KnowledgeBase.enabled.is_(True)
            )
        elif kb_id:
            q = q.join(KnowledgeBase, KnowledgeBase.id == Task.knowledge_base_id).filter(
                Task.knowledge_base_id == kb_id,
                KnowledgeBase.enabled.is_(True)
            )
        else:
            q = q.join(KnowledgeBase, KnowledgeBase.id == Task.knowledge_base_id).filter(
                KnowledgeBase.enabled.is_(True)
            )

        target_chunks = []
        for chunk, task in q.all():
            if (task.file_name or "").upper() != target_file:
                continue
            content = chunk.content or ""
            target_chunks.append({
                "score": 0.0,
                "content": content,
                "chunk_index": chunk.chunk_index,
                "task_id": chunk.task_id,
                "file_name": task.file_name,
                "kb_id": task.knowledge_base_id,
                "section": SearchService.extract_section(content),
                "title_path": SearchService.extract_title_path(content)
            })

        merged_items = cls.merge_adjacent_contexts(expanded_items + target_chunks)

        def score_context(item: dict) -> float:
            """
            说明：score_context 函数，处理当前模块的对应业务步骤。
            """
            file_name = (item.get("file_name") or "").upper()
            section = (item.get("section") or "").lower()
            title_path = (item.get("title_path") or "").lower()
            text = f"{section} {title_path}"
            score = float(item.get("score", 0))
            if file_name == target_file:
                score += 2.4
            if "数据来源" in text or "输入" in text:
                score += 1.2
            if "关键逻辑" in text:
                score += 1.5
            if "study day" in text or "时间点" in text or "时间" in text:
                score += 1.1
            if "输出" in text or "输出文件" in text:
                score += 0.9
            if "常见问题" in text or "q1" in text:
                score += 0.7
            return score

        selected = []
        covered_sections = set()
        current_chars = 0
        for item in sorted(merged_items, key=score_context, reverse=True):
            if (item.get("file_name") or "").upper() != target_file:
                continue
            content = (item.get("content") or "").strip()
            if not content:
                continue
            section_key = ((item.get("section") or "") + "|" + (item.get("title_path") or "")).strip()
            if section_key in covered_sections and len(selected) >= 4:
                continue
            next_total = current_chars + len(content)
            if selected and next_total > cls.MAX_CONTEXT_CHARS + 1200:
                break
            selected.append(item)
            current_chars = next_total
            if section_key:
                covered_sections.add(section_key)
            if len(selected) >= 6:
                break

        return selected or cls.select_contexts(items, session)

    @classmethod
    def select_field_logic_contexts(
        cls,
        query: str,
        session,
        kb_id: str = None,
        task_id: str = None
    ):
        """
        为“某域某字段怎么计算”选择字段级上下文。
        正式环境里这类问题不应依赖普通 top-k 相似度，而应直接锁定目标域文档和目标字段标题/FAQ。
        """
        domain_code = cls.extract_target_domain_code(query)
        field_tokens = cls.extract_field_tokens(query)
        if not domain_code or not field_tokens:
            return []

        target_file = f"{domain_code.upper()}.md"
        primary_field = field_tokens[-1]

        q = session.query(DocumentChunk, Task).join(Task, DocumentChunk.task_id == Task.id)
        if task_id:
            q = q.join(KnowledgeBase, KnowledgeBase.id == Task.knowledge_base_id).filter(
                Task.id == task_id,
                KnowledgeBase.enabled.is_(True)
            )
        elif kb_id:
            q = q.join(KnowledgeBase, KnowledgeBase.id == Task.knowledge_base_id).filter(
                Task.knowledge_base_id == kb_id,
                KnowledgeBase.enabled.is_(True)
            )
        else:
            q = q.join(KnowledgeBase, KnowledgeBase.id == Task.knowledge_base_id).filter(
                KnowledgeBase.enabled.is_(True)
            )

        candidates = []
        for chunk, task in q.all():
            if (task.file_name or "").upper() != target_file:
                continue
            content = chunk.content or ""
            haystack = content.upper()
            if primary_field.upper() not in haystack and not any(token.upper() in haystack for token in field_tokens):
                continue

            section = SearchService.extract_section(content)
            title_path = SearchService.extract_title_path(content)
            score = 0.0
            if primary_field.upper() in (section or "").upper():
                score += 2.4
            if primary_field.upper() in (title_path or "").upper():
                score += 2.0
            if f"Q" in content and primary_field.upper() in haystack:
                score += 1.4
            if "怎么" in content or "如何" in content or "处理" in content or "计算" in content:
                score += 1.0
            score += min(haystack.count(primary_field.upper()) * 0.12, 0.6)

            candidates.append({
                "score": score,
                "content": content,
                "chunk_index": chunk.chunk_index,
                "task_id": chunk.task_id,
                "file_name": task.file_name,
                "kb_id": task.knowledge_base_id,
                "section": section,
                "title_path": title_path
            })

        candidates = cls.merge_adjacent_contexts(sorted(candidates, key=lambda item: float(item.get("score", 0)), reverse=True))
        if candidates:
            return candidates[:6]

        # Operational fallback: the uploaded markdown is the source of the indexed chunks.
        # If a stale/mismatched SQLite path or chunk index misses a target field, keep the
        # answer grounded by reading only the requested domain document, never a broad search.
        upload_path = Path(__file__).resolve().parents[2] / "uploads" / target_file
        if not upload_path.exists():
            return []

        try:
            content = upload_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = upload_path.read_text(encoding="utf-8-sig")
        except OSError:
            return []

        if primary_field.upper() not in content.upper():
            return []

        return [{
            "score": 0.0,
            "content": content,
            "chunk_index": None,
            "task_id": None,
            "file_name": target_file,
            "kb_id": kb_id,
            "section": None,
            "title_path": f"{domain_code.upper()} 域原始文档"
        }]

    @classmethod
    def get_last_assistant_message(cls, history_messages: list | None = None):
        """
        获取最近一条 assistant 消息。
        讲解型追问需要基于上一轮已经回答过的事实，再换一种更容易理解的说法。
        """
        for message in reversed(history_messages or []):
            if getattr(message, "role", None) == "assistant":
                return getattr(message, "content", "") or ""
        return ""

    @classmethod
    def get_last_assistant_structured_message(cls, history_messages: list | None = None):
        """
        说明：get_last_assistant_structured_message 函数，处理当前模块的对应业务步骤。
        """
        for message in reversed(history_messages or []):
            if getattr(message, "role", None) != "assistant":
                continue

            try:
                payload = json.loads(message.answer_payload) if getattr(message, "answer_payload", None) else None
            except Exception:
                payload = None
            try:
                sources = json.loads(message.sources) if getattr(message, "sources", None) else []
            except Exception:
                sources = []

            return {
                "content": getattr(message, "content", "") or "",
                "answer_type": getattr(message, "answer_type", None),
                "answer_payload": payload,
                "sources": sources
            }

        return None

    @classmethod
    def build_diagram_payload_from_previous(cls, query: str, history_messages: list | None = None):
        """
        说明：build_diagram_payload_from_previous 函数，处理当前模块的对应业务步骤。
        """
        previous = cls.get_last_assistant_structured_message(history_messages)
        if not previous:
            return None, None, []

        previous_type = previous.get("answer_type")
        payload = previous.get("answer_payload") or {}
        sources = previous.get("sources") or []
        nodes = []
        edges = []

        def add_node(node_id: str, label: str, detail: str = "", kind: str = "step"):
            """
            说明：add_node 函数，处理当前模块的对应业务步骤。
            """
            text = str(label or "").strip()
            if not text:
                return
            if any(node["id"] == node_id for node in nodes):
                return
            nodes.append({
                "id": node_id,
                "label": text,
                "detail": str(detail or "").strip() or None,
                "kind": kind
            })

        def add_group_nodes(prefix: str, title: str, values: list[str], kind: str):
            """
            说明：add_group_nodes 函数，处理当前模块的对应业务步骤。
            """
            ids = []
            for idx, item in enumerate(values or [], start=1):
                node_id = f"{prefix}{idx}"
                add_node(node_id, title, item, kind)
                ids.append(node_id)
            return ids

        field_name = (payload.get("field_name") or "").strip()
        if previous_type == "field_logic" and field_name:
            add_node("field", f"字段: {field_name}", "上一轮字段逻辑答案", "target")
            dependency_ids = add_group_nodes("dep", "依赖/前置条件", payload.get("dependencies") or [], "input")
            rule_ids = add_group_nodes("rule", "计算/处理规则", payload.get("calculation_rules") or [], "rule")
            special_ids = add_group_nodes("special", "特殊情况", payload.get("special_cases") or [], "condition")
            output_ids = add_group_nodes("out", "相关输出", payload.get("related_outputs") or [], "output")

            ordered_ids = dependency_ids + rule_ids + special_ids + output_ids
            previous_id = "field"
            for node_id in ordered_ids:
                edges.append({"from": previous_id, "to": node_id})
                previous_id = node_id

            title = f"{field_name} 字段逻辑图"
        else:
            add_node("answer", "上一轮答案", previous.get("content"), "target")
            title = "上一轮答案图示"

        if len(nodes) <= 1:
            lines = [line.strip() for line in (previous.get("content") or "").splitlines() if line.strip()]
            for idx, line in enumerate(lines[:6], start=1):
                node_id = f"step{idx}"
                add_node(node_id, f"步骤 {idx}", line, "step")
                if idx == 1:
                    edges.append({"from": "answer", "to": node_id})
                else:
                    edges.append({"from": f"step{idx - 1}", "to": node_id})

        diagram_payload = {
            "diagram_type": "flow",
            "title": title,
            "source_answer_type": previous_type,
            "nodes": nodes,
            "edges": edges
        }
        answer = f"已基于上一轮答案生成图示：{title}"
        return answer, diagram_payload, sources

    @classmethod
    def render_explanation_answer(cls, payload: dict):
        """
        把解释型问题的结构化结果渲染成固定模板。
        缺失项自动省略，避免为了凑模板而编造内容。
        """
        sections = []

        applicable = (payload.get("applicable_stage") or "").strip()
        if applicable:
            sections.append(f"适用阶段\n{applicable}")

        steps = payload.get("calculation_steps") or []
        cleaned_steps = []
        if isinstance(steps, list):
            for item in steps:
                text = str(item or "").strip()
                if text:
                    cleaned_steps.append(text)
        elif isinstance(steps, str) and steps.strip():
            cleaned_steps.append(steps.strip())

        if cleaned_steps:
            body = "\n".join(f"{idx}. {item}" for idx, item in enumerate(cleaned_steps, start=1))
            sections.append(f"计算步骤\n{body}")

        meaning = (payload.get("result_meaning") or "").strip()
        if meaning:
            sections.append(f"结果含义\n{meaning}")

        evidences = payload.get("evidence") or []
        cleaned_evidences = []
        if isinstance(evidences, list):
            for item in evidences:
                text = str(item or "").strip()
                if text:
                    cleaned_evidences.append(text)
        elif isinstance(evidences, str) and evidences.strip():
            cleaned_evidences.append(evidences.strip())

        if cleaned_evidences:
            body = "\n".join(f"- {item}" for item in cleaned_evidences)
            sections.append(f"原文依据\n{body}")

        return "\n\n".join(sections).strip() or None

    @classmethod
    def build_explanation_answer(cls, query: str, contexts: list):
        """
        对解释型问题执行结构化抽取，再由后端渲染成固定模板。
        这是正式项目里常用的做法：模板由后端控制，模型只负责填充字段。
        """
        context_text = cls.build_explanation_context_text(contexts)
        prompt = f"""
你是一个知识整理助手。请基于提供的检索片段，提炼“解释型问题”的结构化答案。

要求：
- 只能使用片段里的信息
- 用中文说明，不要照抄整段代码
- 如果有公式或变量，只能在“原文依据”里简短保留
- 缺失的信息请输出空字符串或空数组，不要编造
- 只输出 JSON，禁止输出 markdown、代码围栏或解释

JSON schema:
{{
  "applicable_stage": "适用阶段，没有就为空字符串",
  "calculation_steps": ["步骤1", "步骤2"],
  "result_meaning": "结果含义，没有就为空字符串",
  "evidence": ["原文依据1", "原文依据2"]
}}

【当前问题】
{query}

【检索片段】
{context_text}
"""
        try:
            raw = (chat(prompt) or "").strip()
        except Exception:
            return None

        if not raw:
            return None

        try:
            payload = json.loads(raw)
        except Exception:
            match = re.search(r"\{[\s\S]*\}", raw)
            if not match:
                return None
            try:
                payload = json.loads(match.group(0))
            except Exception:
                return None

        if not isinstance(payload, dict):
            return None, None

        rendered = cls.render_explanation_answer(payload)
        if not rendered:
            return None, None

        normalized_payload = {
            "applicable_stage": (payload.get("applicable_stage") or "").strip() or None,
            "calculation_steps": [str(item).strip() for item in (payload.get("calculation_steps") or []) if str(item).strip()] or None,
            "result_meaning": (payload.get("result_meaning") or "").strip() or None,
            "evidence": [str(item).strip() for item in (payload.get("evidence") or []) if str(item).strip()] or None
        }
        return rendered, normalized_payload

    @classmethod
    def build_teaching_answer(cls, query: str, contexts: list, history_messages: list | None = None):
        """
        生成“讲给别人听”的版本。
        这种回答允许在事实不变的前提下做表达优化，用更通俗的结构复述上一轮结论。
        """
        previous_answer = cls.get_last_assistant_message(history_messages)
        context_text = cls.build_explanation_context_text(contexts)
        prompt = f"""
你是一个知识讲解助手。

任务：
- 基于上一轮已经确认的事实答案，把内容换成“更容易让别人理解”的说法
- 可以重组表达、增加对比和记忆方式
- 不允许引入检索片段之外的新事实
- 不要简单重复上一轮原句
- 直接输出讲解结果，禁止输出 JSON

建议结构：
1. 先用一句话说明核心区别
2. 再用 2-3 个短点解释怎么区分
3. 如果适合，可加一句“可以这样记”

【上一轮助手回答】
{previous_answer or "无"}

【当前追问】
{query}

【检索片段】
{context_text}
"""
        try:
            answer = (chat(prompt) or "").strip()
        except Exception:
            return None
        return answer or None

    @classmethod
    def render_workflow_summary_answer(cls, payload: dict):
        """
        把流程总结的结构化结果渲染成固定模板。
        允许缺项，但顺序固定，避免“整个流程”回答成零散局部步骤。
        """
        sections = []
        field_map = [
            ("input_sources", "输入来源"),
            ("preprocessing", "数据整理与预处理"),
            ("main_conversion", "主体转换"),
            ("time_and_stage_calculation", "时间与阶段计算"),
            ("special_handling", "特殊处理"),
            ("supplemental_outputs", "补充数据集"),
            ("final_outputs", "输出结果"),
        ]

        for field, title in field_map:
            value = payload.get(field)
            if isinstance(value, list):
                cleaned = [str(item or "").strip() for item in value if str(item or "").strip()]
                if cleaned:
                    body = "\n".join(f"- {item}" for item in cleaned)
                    sections.append(f"{title}\n{body}")
            else:
                text = str(value or "").strip()
                if text:
                    sections.append(f"{title}\n{text}")

        return "\n\n".join(sections).strip() or None

    @classmethod
    def render_domain_relation_answer(cls, payload: dict):
        """
        把域关系问题的结构化结果渲染成固定模板。
        回答主线强调：该域是什么、直接服务哪些域、设计层怎么和它对应、哪些关系不是主关系。
        """
        sections = []
        role = (payload.get("domain_role") or "").strip()
        if role:
            sections.append(f"域角色\n{role}")

        for field, title in [
            ("direct_relations", "直接关系"),
            ("design_relations", "设计层关系"),
            ("non_primary_relations", "非主要关系"),
        ]:
            items = payload.get(field) or []
            cleaned = [str(item or "").strip() for item in items if str(item or "").strip()]
            if cleaned:
                sections.append(f"{title}\n" + "\n".join(f"- {item}" for item in cleaned))

        conclusion = (payload.get("relation_conclusion") or "").strip()
        if conclusion:
            sections.append(f"总结\n{conclusion}")

        return "\n\n".join(sections).strip() or None

    @classmethod
    def render_domain_logic_answer(cls, payload: dict):
        """
        把域级逻辑概览渲染成固定模板。
        这类答案关注“这个域整体怎么工作”，不是单字段解释，也不是全项目流程图。
        """
        sections = []
        role = (payload.get("domain_role") or "").strip()
        if role:
            sections.append(f"域角色\n{role}")

        field_map = [
            ("input_sources", "输入来源"),
            ("core_logic", "核心逻辑"),
            ("time_point_logic", "时间与时间点处理"),
            ("dependencies", "依赖关系"),
            ("outputs", "输出结果"),
        ]
        for field, title in field_map:
            items = payload.get(field) or []
            cleaned = [str(item or "").strip() for item in items if str(item or "").strip()]
            if cleaned:
                sections.append(f"{title}\n" + "\n".join(f"- {item}" for item in cleaned))

        return "\n\n".join(sections).strip() or None

    @classmethod
    def render_field_logic_answer(cls, payload: dict):
        """
        把字段逻辑渲染成固定模板。
        目标是回答“这个字段怎么来、怎么处理、和哪些前置条件有关”，避免再退回泛化解释。
        """
        sections = []
        field_name = (payload.get("field_name") or "").strip()
        if field_name:
            sections.append(f"字段定位\n{field_name}")

        for field, title in [
            ("calculation_rules", "计算/处理规则"),
            ("dependencies", "依赖字段与前置条件"),
            ("special_cases", "特殊情况"),
            ("related_outputs", "相关输出")
        ]:
            items = payload.get(field) or []
            cleaned = [str(item or "").strip() for item in items if str(item or "").strip()]
            if cleaned:
                sections.append(f"{title}\n" + "\n".join(f"- {item}" for item in cleaned))

        return "\n\n".join(sections).strip() or None

    @classmethod
    def extract_domain_code_from_file(cls, file_name: str) -> str | None:
        """
        从文档文件名提取域代码，例如 EX.md -> EX。
        这一步用于把反向引用片段按来源域分组。
        """
        name = (file_name or "").strip()
        match = re.match(r"^([A-Za-z]{2,})\.md$", name, flags=re.IGNORECASE)
        return match.group(1).upper() if match else None

    @classmethod
    def clean_relation_line(cls, line: str) -> str:
        """
        说明：clean_relation_line 函数，处理当前模块的对应业务步骤。
        """
        text = (line or "").strip()
        text = re.sub(r"^[-*#>\s`]+", "", text)
        text = re.sub(r"\*\*", "", text)
        return text.strip()

    @classmethod
    def extract_relation_domain_code(cls, text: str) -> str | None:
        """
        从“DM域：...”这类关系描述里提取域代码。
        用于校验模型输出是否已经覆盖命中的依赖域。
        """
        match = re.match(r"^\s*([A-Za-z]{2,})域", str(text or "").strip(), flags=re.IGNORECASE)
        return match.group(1).upper() if match else None

    @classmethod
    def build_domain_relation_fallbacks(cls, domain_code: str, contexts: list):
        """
        从已命中的上下文中提取最小可信关系事实。
        正式环境里，关系型问题不能完全依赖模型自由总结；如果检索里已经命中了某个域，就至少要把它带出来。
        """
        if not domain_code:
            return []

        grouped = {}
        for context in contexts:
            file_domain = cls.extract_domain_code_from_file(context.get("file_name") or "")
            if not file_domain or file_domain == domain_code.upper():
                continue

            grouped.setdefault(file_domain, []).append(context)

        fallbacks = []
        for file_domain, group_items in grouped.items():
            combined = "\n".join(
                cls.clean_source_text(item.get("content") or "")
                for item in group_items
            )
            lines = [cls.clean_relation_line(line) for line in combined.splitlines() if cls.clean_relation_line(line)]
            upper_text = combined.upper()
            lower_text = combined.lower()
            target_fields = []
            for field in re.findall(rf"\b{domain_code.upper()}(?:STDTC|ENDTC|STDY|RPSTDY)\b", upper_text):
                if field not in target_fields:
                    target_fields.append(field)

            explicit_ex_index = {
                "DM": "DM域：读取 EX 域的首次和末次给药时间（EXSTDTC/EXENDTC），填充 RFXSTDTC 和 RFXENDTC，补充受试动物的人口统计处理时间边界。",
                "BW": "BW域：读取 ex.xpt 中的 EXSTDTC 作为研究参考日，用于计算 BWDY。",
                "BG": "BG域：读取 ex.xpt 中的 EXSTDTC 作为研究参考日，用于计算 BGDY 和 BGENDY。",
                "VS": "VS域：读取 ex.xpt 中的 EXSTDTC/EXENDTC，计算 VSDY 和 VSRFTDTC，并区分 Predose/Postdose 时间点。",
                "CL": "CL域：加载 ex.xpt 获取参考日和给药信息，使用 EXSTDTC/EXENDTC 处理 Predose/Postdose 时间点。",
                "RE": "RE域：读取 ex.xpt 中的 EXSTDTC/EXENDTC，计算 REDY 和 RERFTDTC，并区分 Predose/Postdose 时间点。"
            }
            explicit_target_relations = {"DM", "BW", "BG", "VS", "CL", "RE"}
            direct_signal = any([
                "依赖 EX 域" in combined,
                "依赖EX域" in combined,
                "必须先生成 EX 域" in combined,
                "必须先生成EX域" in combined,
                "ex.xpt" in lower_text,
                "EXSTDTC" in upper_text,
                "EXENDTC" in upper_text
            ])

            if domain_code.upper() == "EX" and file_domain in explicit_target_relations and direct_signal:
                fallbacks.append({
                    "domain": file_domain,
                    "text": explicit_ex_index[file_domain]
                })
                continue

            purpose_line = next((line for line in lines if "用途:" in line and domain_code.lower() in line.lower()), "")
            if not purpose_line:
                purpose_line = next((line for line in lines if "依赖" in line and domain_code.upper() in line.upper()), "")
            if not purpose_line:
                purpose_line = next((line for line in lines if f"{domain_code.lower()}.xpt" in line.lower()), "")
            if not purpose_line:
                purpose_line = next((line for line in lines if any(field in line.upper() for field in target_fields)), "")

            purpose = purpose_line
            if "用途:" in purpose:
                purpose = purpose.split("用途:", 1)[1].strip()
            if "说明:" in purpose:
                purpose = purpose.split("说明:", 1)[1].strip()
            if purpose.startswith("A:"):
                purpose = purpose[2:].strip()

            if not purpose:
                if file_domain == "DM":
                    purpose = "依赖首次和末次给药时间，补充受试动物的处理时间边界"
                elif file_domain in {"BW", "BG"}:
                    purpose = "以首次给药时间作为研究参考日，计算相对研究日"
                elif file_domain in {"VS", "RE"}:
                    purpose = "以给药时间作为参考，计算相对研究日和参考日期时间"
                elif file_domain == "CL":
                    purpose = "加载给药时间作为参考，处理给药前后时间点"
                else:
                    purpose = f"读取 {domain_code.lower()}.xpt 或其时间字段，作为本域计算参考"

            detail_parts = []
            if target_fields:
                detail_parts.append("关键字段: " + "、".join(target_fields))
            if any(flag in upper_text for flag in ["PREDOSE", "POSTDOSE", "EXENDTC"]):
                detail_parts.append("并区分给药前后时点")

            relation = f"{file_domain}域：{purpose}"
            if detail_parts:
                relation += "；" + "，".join(detail_parts)
            fallbacks.append({
                "domain": file_domain,
                "text": relation
            })

        preferred_order = {"DM": 0, "BW": 1, "BG": 2, "VS": 3, "CL": 4, "RE": 5}
        return sorted(
            fallbacks,
            key=lambda item: (preferred_order.get(item["domain"], 99), item["domain"])
        )

    @classmethod
    def build_domain_relation_answer(
        cls,
        query: str,
        contexts: list,
        session,
        kb_id: str = None,
        task_id: str = None
    ):
        """
        对“某个域与其他域是什么关系”执行结构化总结。
        正式环境里，这类问题需要优先综合“别的域如何引用它”，而不是只总结目标域自己的流程。
        """
        domain_code = cls.extract_target_domain_code(query)
        context_text = cls.build_explanation_context_text(contexts)
        reverse_candidates = cls.fetch_domain_relation_candidates(
            domain_code,
            session,
            kb_id=kb_id,
            task_id=task_id
        )
        relation_source_contexts = reverse_candidates + contexts
        fallback_relations = cls.build_domain_relation_fallbacks(domain_code, relation_source_contexts)
        required_domains = [item["domain"] for item in fallback_relations]
        prompt = f"""
你是一个知识关系整理助手。请基于提供的检索片段，总结某个域与其他域的关系。

要求：
- 只能使用片段里的信息
- 优先说明“哪些域直接读取或依赖该域的数据/字段”
- 区分强关系和弱关系，不要把边缘关系写成主关系
- 如果该域和设计域存在“计划 vs 实际执行”关系，也要单独说明
- 如果证据里已经出现这些直接关系域：{", ".join(required_domains) if required_domains else "无"}，`direct_relations` 必须逐一覆盖，不能遗漏
- 缺失的信息输出空数组或空字符串，不要编造
- 只输出 JSON，禁止输出 markdown、代码围栏或解释

JSON schema:
{{
  "target_domain": "{domain_code or ''}",
  "domain_role": "该域在整套转换里的角色定位",
  "direct_relations": [
    "域A：依赖字段/文件 + 作用",
    "域B：依赖字段/文件 + 作用"
  ],
  "design_relations": [
    "设计域/配置域：与目标域的关系"
  ],
  "non_primary_relations": [
    "不是主关系，但需要说明的边界关系"
  ],
  "relation_conclusion": "一句话总结该域和其他域的整体关系"
}}

【当前问题】
{query}

【检索片段】
{context_text}
"""
        try:
            raw = (chat(prompt) or "").strip()
        except Exception:
            return None, None

        if not raw:
            return None, None

        try:
            payload = json.loads(raw)
        except Exception:
            match = re.search(r"\{[\s\S]*\}", raw)
            if not match:
                return None, None
            try:
                payload = json.loads(match.group(0))
            except Exception:
                return None, None

        if not isinstance(payload, dict):
            return None, None

        normalized_payload = {
            "target_domain": (payload.get("target_domain") or domain_code or "").strip() or None,
            "domain_role": (payload.get("domain_role") or "").strip() or None,
            "direct_relations": [str(item).strip() for item in (payload.get("direct_relations") or []) if str(item).strip()] or None,
            "design_relations": [str(item).strip() for item in (payload.get("design_relations") or []) if str(item).strip()] or None,
            "non_primary_relations": [str(item).strip() for item in (payload.get("non_primary_relations") or []) if str(item).strip()] or None,
            "relation_conclusion": (payload.get("relation_conclusion") or "").strip() or None,
        }

        # 正式环境里，“直接关系”不能完全交给模型自由筛选。
        # 如果检索已经命中了明确依赖该域的文档，就应由后端主导把这些关系稳定列出来，
        # 模型只负责补充角色、设计层关系和总结。
        fallback_direct_relations = [item["text"] for item in fallback_relations if item.get("text")]
        model_direct_relations = normalized_payload.get("direct_relations") or []
        merged_direct_relations = []
        covered_domains = set()

        for item in fallback_direct_relations:
            domain = cls.extract_relation_domain_code(item)
            if item not in merged_direct_relations:
                merged_direct_relations.append(item)
            if domain:
                covered_domains.add(domain)

        for item in model_direct_relations:
            domain = cls.extract_relation_domain_code(item)
            if domain and domain in covered_domains:
                continue
            if item not in merged_direct_relations:
                merged_direct_relations.append(item)
            if domain:
                covered_domains.add(domain)

        normalized_payload["direct_relations"] = merged_direct_relations or None

        if not normalized_payload.get("domain_role") and domain_code:
            normalized_payload["domain_role"] = f"{domain_code.upper()}域作为给药时间基准域，为其他域提供研究日和参考时间的计算依据。"

        if not normalized_payload.get("relation_conclusion") and merged_direct_relations:
            relation_domains = "、".join(item["domain"] for item in fallback_relations[:6])
            normalized_payload["relation_conclusion"] = (
                f"{domain_code.upper()}域作为时间基准域，被{relation_domains}等域直接引用，"
                f"用于补充首次/末次给药时间、相对研究日和给药前后参考时点。"
                if domain_code and relation_domains
                else None
            )

        rendered = cls.render_domain_relation_answer(normalized_payload)
        if not rendered:
            return None, None
        return rendered, normalized_payload

    @classmethod
    def build_domain_logic_answer(cls, query: str, contexts: list):
        """
        对“某个域的逻辑是什么”生成域级概览。
        正式环境里这类问题应该返回目标域自身的输入、关键逻辑、时间处理、依赖和输出，而不是混成普通解释问答。
        """
        domain_code = cls.extract_target_domain_code(query)
        context_text = cls.build_explanation_context_text(contexts)
        prompt = f"""
你是一个 SEND 域转换知识整理助手。请基于目标域文档片段，总结这个域本身的主要逻辑。

要求：
- 只能使用片段里的信息
- 重点说明这个域自身如何工作，不要把答案写成跨域关系总结
- 优先覆盖：输入来源、核心转换、时间/时间点处理、依赖关系、输出结果
- 缺失项输出空数组或空字符串，不要编造
- 只输出 JSON，禁止输出 markdown、代码围栏或解释

JSON schema:
{{
  "domain_role": "{domain_code or ''}域在整套转换里的定位",
  "input_sources": ["输入1", "输入2"],
  "core_logic": ["逻辑1", "逻辑2"],
  "time_point_logic": ["时间处理1", "时间处理2"],
  "dependencies": ["依赖1", "依赖2"],
  "outputs": ["输出1", "输出2"]
}}

【当前问题】
{query}

【检索片段】
{context_text}
"""
        try:
            raw = (chat(prompt) or "").strip()
        except Exception:
            return None, None

        if not raw:
            return None, None

        try:
            payload = json.loads(raw)
        except Exception:
            match = re.search(r"\{[\s\S]*\}", raw)
            if not match:
                return None, None
            try:
                payload = json.loads(match.group(0))
            except Exception:
                return None, None

        if not isinstance(payload, dict):
            return None, None

        normalized_payload = {
            "domain_role": (payload.get("domain_role") or "").strip() or None,
            "input_sources": [str(item).strip() for item in (payload.get("input_sources") or []) if str(item).strip()] or None,
            "core_logic": [str(item).strip() for item in (payload.get("core_logic") or []) if str(item).strip()] or None,
            "time_point_logic": [str(item).strip() for item in (payload.get("time_point_logic") or []) if str(item).strip()] or None,
            "dependencies": [str(item).strip() for item in (payload.get("dependencies") or []) if str(item).strip()] or None,
            "outputs": [str(item).strip() for item in (payload.get("outputs") or []) if str(item).strip()] or None,
        }

        rendered = cls.render_domain_logic_answer(normalized_payload)
        if not rendered:
            return None, None
        return rendered, normalized_payload

    @classmethod
    def build_field_logic_answer(cls, query: str, contexts: list):
        """
        对“某域某字段怎么计算/怎么处理”做字段级回答。
        这条链只围绕目标字段本身组织答案。
        """
        field_tokens = cls.extract_field_tokens(query)
        field_name = field_tokens[-1] if field_tokens else ""
        context_text = cls.build_explanation_context_text(contexts)
        prompt = f"""
你是一个 SEND 字段逻辑整理助手。请基于检索片段回答字段 {field_name} 的计算或处理逻辑。

要求：
- 只能使用片段里的信息
- 只围绕目标字段本身回答，不要把其他域或无关 FAQ 混进来
- 优先说明计算/处理规则、依赖字段/前置条件、特殊情况、相关输出
- 缺失项输出空数组或空字符串，不要编造
- 只输出 JSON，禁止输出 markdown、代码围栏或解释

JSON schema:
{{
  "field_name": "{field_name}",
  "calculation_rules": ["规则1", "规则2"],
  "dependencies": ["依赖1", "依赖2"],
  "special_cases": ["特殊情况1"],
  "related_outputs": ["相关输出1"]
}}

【当前问题】
{query}

【检索片段】
{context_text}
"""
        fallback_payload = build_field_logic_payload_from_contexts(field_name, contexts)

        try:
            raw = (chat(prompt) or "").strip()
        except Exception:
            raw = ""

        if not raw:
            if fallback_payload:
                rendered = cls.render_field_logic_answer(fallback_payload)
                return rendered, fallback_payload
            return None, None

        try:
            payload = json.loads(raw)
        except Exception:
            match = re.search(r"\{[\s\S]*\}", raw)
            if not match:
                if fallback_payload:
                    rendered = cls.render_field_logic_answer(fallback_payload)
                    return rendered, fallback_payload
                return None, None
            try:
                payload = json.loads(match.group(0))
            except Exception:
                if fallback_payload:
                    rendered = cls.render_field_logic_answer(fallback_payload)
                    return rendered, fallback_payload
                return None, None

        if not isinstance(payload, dict):
            if fallback_payload:
                rendered = cls.render_field_logic_answer(fallback_payload)
                return rendered, fallback_payload
            return None, None

        normalized_payload = normalize_field_logic_payload(payload, field_name)
        if not has_substantive_field_logic(normalized_payload):
            normalized_payload = fallback_payload or normalized_payload
        elif fallback_payload:
            for key in ["calculation_rules", "dependencies", "special_cases", "related_outputs"]:
                merged = []
                for item in (normalized_payload.get(key) or []) + (fallback_payload.get(key) or []):
                    if item and item not in merged:
                        merged.append(item)
                normalized_payload[key] = merged or None

        rendered = cls.render_field_logic_answer(normalized_payload)
        if not rendered or not has_substantive_field_logic(normalized_payload):
            return None, None
        return rendered, normalized_payload

    @classmethod
    def build_workflow_summary_answer(cls, query: str, contexts: list):
        """
        对“整个流程是什么”这类问题执行专门的流程总结。
        目标是把局部规则提升成输入->处理->输出的完整主线，而不是重复单个阶段细节。
        """
        context_text = cls.build_explanation_context_text(contexts)
        detail_level = cls.get_workflow_detail_level(query)
        detail_rule = (
            "请做详细版流程说明，每个模块尽量写成 2-4 个短点，覆盖关键计算和数据流转。"
            if detail_level == "detailed"
            else "请做简版流程总结，每个模块用 1-2 个短点概括主线。"
        )
        prompt = f"""
你是一个知识整理助手。请基于提供的检索片段，总结某个域或模块的完整流程。

要求：
- 只能使用片段里的信息
- 用中文概括，不要逐字照抄原文
- 要覆盖从输入到输出的主线，而不是只挑局部步骤
- 流程里如果存在时间/阶段/相对日计算，请单独归纳，不要混在普通主体转换里
- 缺失的信息输出空数组或空字符串，不要编造
- {detail_rule}
- 只输出 JSON，禁止输出 markdown、代码围栏或解释

JSON schema:
{{
  "detail_level": "summary 或 detailed",
  "input_sources": ["输入来源1", "输入来源2"],
  "preprocessing": ["数据整理步骤1", "数据整理步骤2"],
  "main_conversion": ["主体转换步骤1", "主体转换步骤2"],
  "time_and_stage_calculation": ["时间或阶段计算1", "时间或阶段计算2"],
  "special_handling": ["特殊处理1", "特殊处理2"],
  "supplemental_outputs": ["补充数据集或补充输出1"],
  "final_outputs": ["最终输出1", "最终输出2"]
}}

【当前问题】
{query}

【检索片段】
{context_text}
"""
        try:
            raw = (chat(prompt) or "").strip()
        except Exception:
            return None

        if not raw:
            return None

        try:
            payload = json.loads(raw)
        except Exception:
            match = re.search(r"\{[\s\S]*\}", raw)
            if not match:
                return None
            try:
                payload = json.loads(match.group(0))
            except Exception:
                return None

        if not isinstance(payload, dict):
            return None

        normalized_payload = {
            "detail_level": payload.get("detail_level") or detail_level,
            "input_sources": [str(item).strip() for item in (payload.get("input_sources") or []) if str(item).strip()] or None,
            "preprocessing": [str(item).strip() for item in (payload.get("preprocessing") or []) if str(item).strip()] or None,
            "main_conversion": [str(item).strip() for item in (payload.get("main_conversion") or []) if str(item).strip()] or None,
            "time_and_stage_calculation": [str(item).strip() for item in (payload.get("time_and_stage_calculation") or []) if str(item).strip()] or None,
            "special_handling": [str(item).strip() for item in (payload.get("special_handling") or []) if str(item).strip()] or None,
            "supplemental_outputs": [str(item).strip() for item in (payload.get("supplemental_outputs") or []) if str(item).strip()] or None,
            "final_outputs": [str(item).strip() for item in (payload.get("final_outputs") or []) if str(item).strip()] or None,
        }
        rendered = cls.render_workflow_summary_answer(normalized_payload)
        if not rendered:
            return None, None
        return rendered, normalized_payload

    @classmethod
    def detect_answer_type(cls, query: str, answer: str, answer_payload: dict | None = None, mode: str | None = None):
        """
        统一定义答案类型，避免前端再去猜测文案结构。
        """
        if mode:
            return mode
        if cls.is_field_logic_query(query):
            return "field_logic"
        if cls.is_domain_logic_query(query):
            return "domain_logic"
        if cls.is_domain_relation_query(query):
            return "domain_relation"
        if answer_payload:
            return "explanation"
        if cls.is_teaching_query(query):
            return "teaching"
        if cls.is_file_spec_query(query):
            return "file_spec"
        if cls.is_listing_query(query):
            return "list"
        return "text"

    @classmethod
    def rewrite_query(cls, query: str, history_messages: list | None = None):
        """
        说明：rewrite_query 函数，处理当前模块的对应业务步骤。
        """
        if not cls.should_rewrite_query(query, history_messages):
            return query

        history_text = cls.render_history(history_messages or [])
        prompt = f"""
你是检索前的问题改写助手。

任务：
- 结合最近会话，把“当前问题”改写成一个可独立检索的完整问题
- 保留原始意图，不要扩展，不要回答问题
- 如果当前问题本身已经完整清楚，原样返回
- 只输出改写后的单行问题，禁止解释

【最近会话】
{history_text or "无"}

【当前问题】
{query}
"""

        try:
            rewritten = (chat(prompt) or "").strip()
        except Exception:
            return query

        if not rewritten:
            return query

        rewritten = rewritten.replace("\n", " ").strip()
        if len(rewritten) > 200:
            return query

        original_domain = cls.extract_target_domain_code(query)
        rewritten_domain = cls.extract_target_domain_code(rewritten)
        if original_domain and rewritten_domain and original_domain != rewritten_domain:
            return query
        if original_domain and not rewritten_domain:
            return query

        original_fields = cls.extract_field_tokens(query)
        rewritten_upper = rewritten.upper()
        if original_fields and not all(field in rewritten_upper for field in original_fields):
            return query

        return rewritten

    @classmethod
    def build_prompt(cls, query: str, contexts: list, tone: str = None, history_messages: list | None = None):
        """
        说明：build_prompt 函数，处理当前模块的对应业务步骤。
        """
        rendered_contexts = []

        for idx, context in enumerate(contexts, start=1):
            section = context.get("section") or "-"
            file_name = context.get("file_name") or "-"
            content = (context.get("content") or "").strip()
            rendered_contexts.append(
                f"【片段{idx}】\n"
                f"文件: {file_name}\n"
                f"章节: {section}\n"
                f"内容:\n{content}"
            )

        context_text = "\n\n".join(rendered_contexts)
        if cls.is_listing_query(query):
            answer_shape = "如果问题是在询问“有哪些/包含哪些/列出”，请按 1. 2. 3. 的编号列表完整列出要点，优先覆盖所有要点，再补充简要说明。"
        elif cls.is_explanation_query(query):
            answer_shape = (
                "请用中文解释计算逻辑，优先说明每一步在做什么、输入是什么、结果怎么得到。"
                "如果原文里有公式或代码，只能作为辅助说明简短引用，不要整段照抄代码块，不要把英文变量名堆成答案主体。"
            )
        else:
            answer_shape = "请直接回答问题，必要时引用关键原文。"
        tone_rule_map = {
            "严谨": "回答要严谨、克制，优先给出精确表述，不做延伸发挥。",
            "简洁": "回答要简洁，先给结论，再保留最必要的依据。",
            "客服": "回答要友好易懂，但仍然必须严格基于原文。"
        }
        tone_rule = tone_rule_map.get(tone or "", "回答要清晰直接，严格基于原文。")
        history_text = cls.render_history(history_messages or [])
        numbered_items = cls.extract_top_level_numbered_items(contexts)
        numbered_items_text = "\n".join(numbered_items) if numbered_items else "无"

        return f"""
    你是一个严格基于知识库回答问题的助手。

    【强制规则】
    - 只能从提供的内容中找答案
    - 不允许使用外部知识
    - 必须从原文中提取答案
    - 不允许改写含义
    - 如果答案分散在多个片段中，可以合并多个片段作答，但必须明确基于原文
    - 如果片段之间信息冲突，优先保留更直接、更完整的原文表述
    - 优先使用与问题最直接相关、且能覆盖完整语义的片段
    - 不要被文档标题、总控说明、重复 overlap 文本带偏
    - 如果用户要求“解释 / 用中文说明逻辑”，必须先给中文解释，再视需要补充公式或变量名
    - 解释型问题不要直接输出整段代码块；除非用户明确要求贴原文代码
    - {tone_rule}

    如果找不到明确答案，才回答：无法确定。

    【最近会话】
    {history_text or "无历史会话"}

    【一级编号项提示】
    {numbered_items_text}

    【检索片段】
    {context_text}

    【当前问题】
    {query}

    【回答方式】
    {answer_shape}

    请基于以上片段直接给出答案；不要编造未出现的信息，不要遗漏明显存在的并列要点。
    如果原文已经有一级编号，请保留原始编号顺序；不要把子 bullet、解释句或字段说明重新编号成新的一级条目。
    """

    @classmethod
    def answer_query(
        cls,
        query: str,
        session,
        kb_id: str = None,
        task_id: str = None,
        tone: str = None,
        top_k: int = 5,
        history_messages: list | None = None
    ):
        """
        说明：answer_query 函数，处理当前模块的对应业务步骤。
        """
        if cls.is_visualization_query(query) and history_messages:
            diagram_answer, diagram_payload, previous_sources = cls.build_diagram_payload_from_previous(
                query,
                history_messages=history_messages
            )
            if diagram_answer and diagram_payload:
                return {
                    "query": query,
                    "rewritten_query": None,
                    "answer": diagram_answer,
                    "answer_type": "diagram",
                    "answer_payload": diagram_payload,
                    "sources": previous_sources,
                    "contexts": []
                }

        rewritten_query = cls.rewrite_query(query, history_messages)
        effective_query = rewritten_query or query
        intent = cls.classify_query_intent(effective_query)
        search_top_k = top_k
        if intent == "field_logic":
            search_top_k = max(search_top_k, 8)
        if intent == "file_spec":
            search_top_k = max(search_top_k, 8)
        if intent == "workflow_summary":
            search_top_k = max(search_top_k, 12)
        if intent == "domain_relation":
            search_top_k = max(search_top_k, 14)
        if intent == "domain_logic":
            search_top_k = max(search_top_k, 10)
        search_result = SearchService.search(
            query=rewritten_query,
            session=session,
            kb_id=kb_id,
            task_id=task_id,
            top_k=search_top_k
        )

        items = search_result.get("items", [])

        if not items:
            return {
                "query": query,
                "rewritten_query": rewritten_query if rewritten_query != query else None,
                "answer": "当前知识库没有检索到相关内容。",
                "sources": [],
                "contexts": []
            }

        if intent == "field_logic":
            contexts = cls.select_field_logic_contexts(
                effective_query,
                session,
                kb_id=kb_id,
                task_id=task_id
            )
            if not contexts:
                domain_code = cls.extract_target_domain_code(effective_query)
                field_tokens = cls.extract_field_tokens(effective_query)
                field_name = field_tokens[-1] if field_tokens else ""
                target = f"{domain_code or ''}域 {field_name}".strip()
                return {
                    "query": query,
                    "rewritten_query": rewritten_query if rewritten_query != query else None,
                    "answer": f"无法确定：当前知识库没有检索到 {target} 的明确字段逻辑。",
                    "answer_type": "field_logic",
                    "answer_payload": {
                        "field_name": field_name or None,
                        "calculation_rules": None,
                        "dependencies": None,
                        "special_cases": None,
                        "related_outputs": None
                    },
                    "sources": [],
                    "contexts": []
                }
        elif intent == "domain_relation":
            contexts = cls.select_domain_relation_contexts(
                effective_query,
                items,
                session,
                kb_id=kb_id,
                task_id=task_id
            )
        elif intent == "workflow_summary":
            contexts = cls.select_workflow_contexts(items, session)
        elif intent == "domain_logic":
            contexts = cls.select_domain_logic_contexts(
                effective_query,
                items,
                session,
                kb_id=kb_id,
                task_id=task_id
            )
        else:
            contexts = cls.select_contexts(items, session)
        sources = cls.build_sources(contexts)

        structured_answer = None
        if intent == "list":
            structured_answer = cls.build_structured_list_answer(contexts)

        file_spec_answer = None
        if intent == "file_spec":
            file_spec_answer = cls.build_file_spec_answer(effective_query, contexts, task_id=task_id)

        teaching_answer = None
        if cls.is_teaching_query(query):
            teaching_answer = cls.build_teaching_answer(query, contexts, history_messages=history_messages)

        explanation_answer = None
        explanation_payload = None
        if intent == "explanation":
            explanation_answer, explanation_payload = cls.build_explanation_answer(effective_query, contexts)

        workflow_answer = None
        workflow_payload = None
        if intent == "workflow_summary":
            workflow_answer, workflow_payload = cls.build_workflow_summary_answer(effective_query, contexts)

        domain_relation_answer = None
        domain_relation_payload = None
        if intent == "domain_relation":
            domain_relation_answer, domain_relation_payload = cls.build_domain_relation_answer(
                effective_query,
                contexts,
                session,
                kb_id=kb_id,
                task_id=task_id
            )

        domain_logic_answer = None
        domain_logic_payload = None
        if intent == "domain_logic":
            domain_logic_answer, domain_logic_payload = cls.build_domain_logic_answer(effective_query, contexts)

        field_logic_answer = None
        field_logic_payload = None
        if intent == "field_logic":
            field_logic_answer, field_logic_payload = cls.build_field_logic_answer(effective_query, contexts)

        answer_mode = None
        if file_spec_answer:
            answer = file_spec_answer
            answer_mode = "file_spec"
        elif teaching_answer:
            answer = teaching_answer
            answer_mode = "teaching"
        elif domain_relation_answer:
            answer = domain_relation_answer
            answer_mode = "domain_relation"
        elif field_logic_answer:
            answer = field_logic_answer
            answer_mode = "field_logic"
        elif domain_logic_answer:
            answer = domain_logic_answer
            answer_mode = "domain_logic"
        elif workflow_answer:
            answer = workflow_answer
            answer_mode = "workflow_summary"
        elif explanation_answer:
            answer = explanation_answer
            answer_mode = "explanation"
        elif structured_answer:
            answer = structured_answer
            answer_mode = "list"
        else:
            prompt = cls.build_prompt(query, contexts, tone=tone, history_messages=history_messages)
            answer = chat(prompt)
            answer_mode = "text"

        if answer_mode == "workflow_summary":
            final_payload = workflow_payload
        elif answer_mode == "domain_relation":
            final_payload = domain_relation_payload
        elif answer_mode == "field_logic":
            final_payload = field_logic_payload
        elif answer_mode == "domain_logic":
            final_payload = domain_logic_payload
        else:
            final_payload = explanation_payload
        answer_type = cls.detect_answer_type(effective_query, answer, final_payload, mode=answer_mode)

        return {
            "query": query,
            "rewritten_query": rewritten_query if rewritten_query != query else None,
            "answer": answer,
            "answer_type": answer_type,
            "answer_payload": final_payload,
            "sources": sources,
            "contexts": contexts
        }

    @classmethod
    def serialize_message(cls, message: ConversationMessage):
        """
        说明：serialize_message 函数，处理当前模块的对应业务步骤。
        """
        try:
            sources = json.loads(message.sources) if message.sources else []
        except Exception:
            sources = []
        try:
            answer_payload = json.loads(message.answer_payload) if message.answer_payload else None
        except Exception:
            answer_payload = None

        return {
            "id": message.id,
            "role": message.role,
            "content": message.content,
            "answer_type": message.answer_type,
            "answer_payload": answer_payload,
            "sources": sources,
            "created_at": cls._format_dt(message.created_at)
        }

    @classmethod
    def qa(cls, query: str, session, kb_id: str = None, task_id: str = None, tone: str = None, top_k: int = 5):
        """
        说明：qa 函数，处理当前模块的对应业务步骤。
        """
        qa_result = cls.answer_query(query, session, kb_id=kb_id, task_id=task_id, tone=tone, top_k=top_k)
        EvaluationService.log_qa_turn(
            session,
            conversation_id=None,
            user_message_id=None,
            assistant_message_id=None,
            kb_id=kb_id,
            query=query,
            rewritten_query=qa_result.get("rewritten_query"),
            answer=qa_result["answer"],
            answer_type=qa_result.get("answer_type"),
            sources=qa_result["sources"]
        )
        return qa_result

    @classmethod
    def create_conversation(cls, req, session):
        """
        说明：create_conversation 函数，处理当前模块的对应业务步骤。
        """
        now = datetime.now()
        conversation = Conversation(
            id=str(uuid.uuid4()),
            title=req.title or "新会话",
            kb_id=req.kb_id,
            tone=req.tone,
            created_at=now,
            updated_at=now
        )
        session.add(conversation)
        session.commit()
        session.refresh(conversation)

        return {
            "id": conversation.id,
            "title": conversation.title,
            "kb_id": conversation.kb_id,
            "tone": conversation.tone,
            "created_at": cls._format_dt(conversation.created_at),
            "updated_at": cls._format_dt(conversation.updated_at),
            "last_message": None
        }

    @classmethod
    def list_conversations(cls, session):
        """
        说明：list_conversations 函数，处理当前模块的对应业务步骤。
        """
        conversations = session.query(Conversation).order_by(Conversation.updated_at.desc()).all()
        items = []

        for conversation in conversations:
            last_message = session.query(ConversationMessage) \
                .filter(ConversationMessage.conversation_id == conversation.id) \
                .order_by(ConversationMessage.created_at.desc()) \
                .first()

            items.append({
                "id": conversation.id,
                "title": conversation.title or "新会话",
                "kb_id": conversation.kb_id,
                "tone": conversation.tone,
                "created_at": cls._format_dt(conversation.created_at),
                "updated_at": cls._format_dt(conversation.updated_at),
                "last_message": last_message.content[:80] if last_message else None
            })

        return items

    @classmethod
    def get_conversation_messages(cls, conversation_id: str, session):
        """
        说明：get_conversation_messages 函数，处理当前模块的对应业务步骤。
        """
        cls.get_conversation_or_404(conversation_id, session)
        messages = session.query(ConversationMessage) \
            .filter(ConversationMessage.conversation_id == conversation_id) \
            .order_by(ConversationMessage.created_at.asc()) \
            .all()

        return {
            "conversation_id": conversation_id,
            "messages": [cls.serialize_message(message) for message in messages]
        }

    @classmethod
    def create_conversation_turn(cls, conversation_id: str, req, session):
        """
        说明：create_conversation_turn 函数，处理当前模块的对应业务步骤。
        """
        conversation = cls.get_conversation_or_404(conversation_id, session)
        content = (req.content or "").strip()
        if not content:
            raise HTTPException(status_code=400, detail="content is required")

        now = datetime.now()
        if conversation.title in (None, "", "新会话"):
            conversation.title = cls.build_conversation_title(content)

        if req.kb_id:
            conversation.kb_id = req.kb_id
        if req.tone:
            conversation.tone = req.tone

        user_message = ConversationMessage(
            id=str(uuid.uuid4()),
            conversation_id=conversation.id,
            role="user",
            content=content,
            sources=None,
            created_at=now
        )
        session.add(user_message)
        session.commit()
        session.refresh(user_message)

        history_messages = session.query(ConversationMessage) \
            .filter(ConversationMessage.conversation_id == conversation.id) \
            .order_by(ConversationMessage.created_at.asc()) \
            .all()

        qa_result = cls.answer_query(
            content,
            session,
            kb_id=req.kb_id or conversation.kb_id,
            task_id=req.task_id,
            tone=req.tone or conversation.tone,
            top_k=req.top_k,
            history_messages=history_messages[:-1]
        )

        assistant_message = ConversationMessage(
            id=str(uuid.uuid4()),
            conversation_id=conversation.id,
            role="assistant",
            content=qa_result["answer"],
            answer_type=qa_result.get("answer_type"),
            answer_payload=json.dumps(qa_result.get("answer_payload"), ensure_ascii=False) if qa_result.get("answer_payload") else None,
            sources=json.dumps(qa_result["sources"], ensure_ascii=False),
            created_at=datetime.now()
        )
        session.add(assistant_message)

        conversation.updated_at = datetime.now()
        session.commit()
        session.refresh(assistant_message)
        session.refresh(conversation)

        EvaluationService.log_qa_turn(
            session,
            conversation_id=conversation.id,
            user_message_id=user_message.id,
            assistant_message_id=assistant_message.id,
            kb_id=req.kb_id or conversation.kb_id,
            query=content,
            rewritten_query=qa_result.get("rewritten_query"),
            answer=qa_result["answer"],
            answer_type=qa_result.get("answer_type"),
            sources=qa_result["sources"]
        )

        return {
            "conversation_id": conversation.id,
            "rewritten_query": qa_result.get("rewritten_query"),
            "user_message": cls.serialize_message(user_message),
            "assistant_message": cls.serialize_message(assistant_message)
        }
