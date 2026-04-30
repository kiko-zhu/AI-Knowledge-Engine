# app/modules/search/service.py
import json
import re

import jieba
from sklearn.metrics.pairwise import cosine_similarity

from app.core.embedding import get_embedding
from app.modules.task.model import DocumentChunk, KnowledgeBase, Task


class SearchService:
    """
    说明：SearchService 类，封装当前模块的数据结构或业务逻辑。
    """
    @classmethod
    def extract_section(cls, content: str):
        """
        从 chunk 文本中提取当前章节标题。
        这个字段用于检索加权和前端来源展示。
        """
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("#"):
                return line.replace("#", "").strip()
        return None

    @classmethod
    def extract_title_path(cls, content: str):
        """
        从 chunk 文本中提取“标题路径”元信息。
        这类路径对结构化文档问答很重要，常用于章节命中提权。
        """
        marker = "标题路径:"
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith(marker):
                return stripped.replace(marker, "").strip()
        return ""

    @classmethod
    def normalize_text(cls, value: str):
        """
        统一把文本标准化成可比较的小写字符串，减少命中判断时的格式噪声。
        """
        return (value or "").strip().lower()

    @classmethod
    def extract_keywords(cls, query: str):
        """
        从用户问题中提取关键词。
        这里同时兼容原始 query、jieba 分词、大写字段名和英文标识符。
        """
        query = (query or "").strip()
        keywords = []

        if query:
            keywords.append(query)

        tokenizer = getattr(jieba, "lcut", None)
        tokens = tokenizer(query) if callable(tokenizer) else list(jieba.cut(query))

        for token in tokens:
            token = token.strip()
            if len(token) >= 2 and token not in keywords:
                keywords.append(token)

        for token in re.findall(r"[A-Z]{2,}[A-Z0-9_]*", query):
            if token not in keywords:
                keywords.append(token)

        for token in re.findall(r"[a-zA-Z_]{3,}", query):
            if token not in keywords:
                keywords.append(token)

        return keywords

    @classmethod
    def lexical_score(cls, query: str, content: str, section: str, title_path: str):
        """
        计算词法命中得分。
        这个分数和 embedding 相似度一起组成最终排序，改善结构化文档的章节命中效果。
        """
        query_text = cls.normalize_text(query)
        content_text = cls.normalize_text(content)
        section_text = cls.normalize_text(section)
        title_text = cls.normalize_text(title_path)

        keywords = cls.extract_keywords(query)
        if not keywords:
            return 0.0

        score = 0.0

        if query_text and query_text in content_text:
            score += 0.28
        if query_text and query_text in section_text:
            score += 0.35
        if query_text and query_text in title_text:
            score += 0.35

        hit_count = 0
        for keyword in keywords:
            token = cls.normalize_text(keyword)
            if not token:
                continue

            if token in title_text:
                score += 0.18
                hit_count += 1
                continue

            if token in section_text:
                score += 0.16
                hit_count += 1
                continue

            if token in content_text:
                score += 0.08
                hit_count += 1

        if hit_count:
            score += min(hit_count / max(len(keywords), 1), 1.0) * 0.12

        # “有哪些/关键逻辑/输出列/结果字段” 这类结构化问法，
        # 更依赖章节标题命中，而不是纯正文相似度。
        structure_flags = [
            "关键逻辑", "输出列", "结果字段", "POOLDEF", "总控", "未映射", "字段",
            "输出文件", "文件路径", "文件格式", "路径", "格式"
        ]
        if any(flag.lower() in query_text for flag in [item.lower() for item in structure_flags]):
            if any(flag.lower() in section_text for flag in [item.lower() for item in structure_flags]):
                score += 0.18
            if any(flag.lower() in title_text for flag in [item.lower() for item in structure_flags]):
                score += 0.18

        return score

    @classmethod
    def search(cls, query: str, session, kb_id: str = None, task_id: str = None, top_k: int = 5):
        """
        执行知识库检索。
        如果指定 task_id，只在该文档任务内检索；
        否则如果指定 kb_id，只在该知识库内检索；
        否则只检索当前处于 enabled=true 的知识库。
        """
        query_vec = get_embedding(query)

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

        rows = q.all()
        results = []

        for chunk, task in rows:
            try:
                emb = json.loads(chunk.embedding)
                embedding_score = float(cosine_similarity([query_vec], [emb])[0][0])
            except Exception:
                continue

            content = chunk.content or ""
            section = cls.extract_section(content)
            title_path = cls.extract_title_path(content)
            lexical = cls.lexical_score(query, content, section or "", title_path or "")

            # embedding 仍然是主干，但不再一票否决。
            # 对结构化知识文档，标题/章节命中经常比正文相似度更重要。
            final_score = embedding_score * 0.72 + lexical

            results.append({
                "score": float(final_score),
                "content": content,
                "chunk_index": chunk.chunk_index,
                "task_id": chunk.task_id,
                "file_name": task.file_name if task else None,
                "kb_id": task.knowledge_base_id if task else None,
                "section": section,
                "title_path": title_path
            })

        results = sorted(results, key=lambda x: x["score"], reverse=True)

        return {
            "query": query,
            "top_k": top_k,
            "items": results[:top_k]
        }
