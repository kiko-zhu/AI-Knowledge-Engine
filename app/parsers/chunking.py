import re


HEADER_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
LIST_RE = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+")
CODE_FENCE_RE = re.compile(r"^\s*```")


def normalize_content(content: str) -> str:
    """
    说明：normalize_content 函数，处理当前模块的对应业务步骤。
    """
    return content.replace("\r\n", "\n").replace("\r", "\n")


def split_into_sections(content: str):
    """
    按 Markdown 标题切分 section，并保留标题层级路径。
    这样后续每个 chunk 都能带上“父标题 -> 子标题”的上下文。
    """
    lines = normalize_content(content).split("\n")
    sections = []
    header_stack = []
    current_lines = []
    in_code_block = False

    def flush_current():
        """
        说明：flush_current 函数，处理当前模块的对应业务步骤。
        """
        text = "\n".join(current_lines).strip()
        if text:
            sections.append({
                "path": [item["title"] for item in header_stack],
                "text": text,
            })

    for line in lines:
        if CODE_FENCE_RE.match(line):
            in_code_block = not in_code_block

        header_match = HEADER_RE.match(line)
        if header_match and not in_code_block:
            flush_current()
            current_lines = []

            level = len(header_match.group(1))
            title = header_match.group(2).strip()

            while header_stack and header_stack[-1]["level"] >= level:
                header_stack.pop()
            header_stack.append({"level": level, "title": title})

            current_lines.append(line)
        else:
            current_lines.append(line)

    flush_current()
    return sections


def split_markdown_blocks(text: str):
    """
    在 section 内优先按“代码块 / 列表块 / 普通段落”切，
    尽量不要在业务步骤、代码片段中间硬切断。
    """
    lines = text.split("\n")
    blocks = []
    current = []
    mode = None
    in_code_block = False

    def flush():
        """
        说明：flush 函数，处理当前模块的对应业务步骤。
        """
        nonlocal current, mode
        block = "\n".join(current).strip()
        if block:
            blocks.append(block)
        current = []
        mode = None

    def line_indent(value: str) -> int:
        """
        说明：line_indent 函数，处理当前模块的对应业务步骤。
        """
        return len(value) - len(value.lstrip(" \t"))

    list_base_indent = None

    for line in lines:
        if CODE_FENCE_RE.match(line):
            if not in_code_block:
                flush()
                in_code_block = True
                mode = "code"
                current.append(line)
            else:
                current.append(line)
                flush()
                in_code_block = False
            continue

        if in_code_block:
            current.append(line)
            continue

        if not line.strip():
            flush()
            continue

        if HEADER_RE.match(line):
            flush()
            current.append(line)
            flush()
            continue

        if LIST_RE.match(line):
            # 每个顶层列表项都尽量拆成独立 block。
            # 这样“4. 输出列: ...”不会和“5. POOLDEF 输出: ...”拼成一个大块，
            # 后续即便超长，也会优先保留单条列表项的完整语义。
            indent = line_indent(line)

            if mode == "list" and current and list_base_indent is not None and indent <= list_base_indent:
                flush()

            if mode not in (None, "list"):
                flush()
            mode = "list"
            list_base_indent = indent
            current.append(line)
            continue

        if mode == "list":
            # 列表项的续行、子 bullet、代码缩进都归到当前列表项中；
            # 一旦回到同级普通文本，再结束当前列表项。
            if line.startswith(" ") or line.startswith("\t"):
                current.append(line)
                continue
            flush()
            list_base_indent = None

        if mode not in (None, "paragraph"):
            flush()

        mode = "paragraph"
        current.append(line)

    flush()
    return blocks


def is_list_block(text: str) -> bool:
    """
    说明：is_list_block 函数，处理当前模块的对应业务步骤。
    """
    first_line = next((line for line in text.split("\n") if line.strip()), "")
    return bool(LIST_RE.match(first_line))


def is_ordered_list_block(text: str) -> bool:
    """
    说明：is_ordered_list_block 函数，处理当前模块的对应业务步骤。
    """
    first_line = next((line for line in text.split("\n") if line.strip()), "")
    return bool(re.match(r"^\s*\d+\.\s+", first_line))


def split_long_block(text: str, max_len=800, break_chars=None):
    """
    单个 block 仍然过长时，优先在换行/句号等自然边界处分裂，
    实在找不到再退化为定长切分。
    """
    chunks = []
    remaining = text.strip()
    min_split = max(int(max_len * 0.55), 120)
    break_chars = break_chars or "\n。！？；.;:： "

    while len(remaining) > max_len:
        window = remaining[:max_len]
        split_at = -1

        for idx in range(len(window) - 1, min_split - 1, -1):
            if window[idx] in break_chars:
                split_at = idx + 1
                break

        if split_at == -1:
            split_at = max_len

        chunk = remaining[:split_at].strip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[split_at:].strip()

    if remaining:
        chunks.append(remaining)

    return chunks


def build_chunk_text(path, text):
    """
    给 chunk 加上标题路径，便于检索时保留层级上下文。
    """
    if not path:
        return text.strip()
    path_text = " > ".join(path)
    return f"标题路径: {path_text}\n\n{text.strip()}"


def smart_split(content: str, max_len=800):
    """
    面向结构化 Markdown 的切分策略：
    1. 先按标题分 section
    2. section 内按代码块/列表/段落分 block
    3. 只有 block 过长时才做软切分
    """
    final_chunks = []
    sections = split_into_sections(content)

    for section in sections:
        path = section["path"]
        blocks = split_markdown_blocks(section["text"])
        current_chunk = ""

        for block in blocks:
            candidate = block if not current_chunk else f"{current_chunk}\n\n{block}"
            candidate_text = build_chunk_text(path, candidate)

            if len(candidate_text) <= max_len:
                current_chunk = candidate
                continue

            if current_chunk:
                final_chunks.append(build_chunk_text(path, current_chunk))
                current_chunk = ""

            block_text = build_chunk_text(path, block)
            # 长字段清单/长编号步骤在检索里应尽量作为整体保留，
            # 否则很容易在逗号分隔的字段名之间断开，破坏语义。
            keep_limit = int(max_len * (1.9 if is_ordered_list_block(block_text) else 1.6))
            if is_list_block(block_text) and len(block_text) <= keep_limit:
                final_chunks.append(block_text)
                continue

            if len(block_text) <= max_len:
                current_chunk = block
                continue

            split_chars = "\n。！？；.;:： " if not is_list_block(block) else "\n。！？；.;"
            for piece in split_long_block(block, max_len=max_len - 40, break_chars=split_chars):
                final_chunks.append(build_chunk_text(path, piece))

        if current_chunk:
            final_chunks.append(build_chunk_text(path, current_chunk))

    return final_chunks


def add_overlap(chunks, overlap=120):
    """
    overlap 仍然保留，但只拼接上一块的尾部，避免完全丢失跨块上下文。
    这里不再依赖固定段落结构，保持实现简单稳定。
    """
    result = []

    for i, chunk in enumerate(chunks):
        if i == 0:
            result.append(chunk)
            continue

        prev = chunks[i - 1]
        overlap_text = prev[-overlap:].strip()
        result.append(f"{overlap_text}\n\n{chunk}")

    return result


def split_for_rag(content: str):
    """
    说明：split_for_rag 函数，处理当前模块的对应业务步骤。
    """
    chunks = smart_split(content)
    chunks = add_overlap(chunks)
    return chunks
