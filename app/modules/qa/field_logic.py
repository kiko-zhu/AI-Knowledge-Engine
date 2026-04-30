import re


def normalize_field_logic_payload(payload: dict | None, field_name: str) -> dict:
    """
    说明：normalize_field_logic_payload 函数，处理当前模块的对应业务步骤。
    """
    payload = payload if isinstance(payload, dict) else {}
    return {
        "field_name": (payload.get("field_name") or field_name or "").strip() or None,
        "calculation_rules": [
            str(item).strip()
            for item in (payload.get("calculation_rules") or [])
            if str(item).strip()
        ] or None,
        "dependencies": [
            str(item).strip()
            for item in (payload.get("dependencies") or [])
            if str(item).strip()
        ] or None,
        "special_cases": [
            str(item).strip()
            for item in (payload.get("special_cases") or [])
            if str(item).strip()
        ] or None,
        "related_outputs": [
            str(item).strip()
            for item in (payload.get("related_outputs") or [])
            if str(item).strip()
        ] or None,
    }


def has_substantive_field_logic(payload: dict | None) -> bool:
    """
    说明：has_substantive_field_logic 函数，处理当前模块的对应业务步骤。
    """
    if not isinstance(payload, dict):
        return False
    return any(payload.get(key) for key in [
        "calculation_rules",
        "dependencies",
        "special_cases",
        "related_outputs",
    ])


def clean_markdown_line(line: str) -> str:
    """
    说明：clean_markdown_line 函数，处理当前模块的对应业务步骤。
    """
    text = (line or "").strip()
    text = re.sub(r"^[-*+]\s+", "", text)
    text = re.sub(r"^\d+\.\s+", "", text)
    text = text.replace("**", "")
    text = text.replace("`", "")
    return text.strip()


def append_unique(items: list[str], value: str):
    """
    说明：append_unique 函数，处理当前模块的对应业务步骤。
    """
    text = clean_markdown_line(value)
    if text and text not in items:
        items.append(text)


def extract_field_windows(content: str, field_name: str) -> list[list[str]]:
    """
    说明：extract_field_windows 函数，处理当前模块的对应业务步骤。
    """
    field = (field_name or "").upper()
    if not field:
        return []

    lines = (content or "").splitlines()
    windows = []
    indexes = [idx for idx, line in enumerate(lines) if field in line.upper()]

    for idx in indexes:
        start = idx
        end = min(len(lines), idx + 12)

        for probe in range(idx + 1, min(len(lines), idx + 24)):
            stripped = lines[probe].strip()
            if not stripped:
                continue
            if stripped.startswith("##### ") or stripped.startswith("#### "):
                end = probe
                break
            if stripped.startswith("**") and field not in stripped.upper():
                end = probe
                break

        window = lines[start:end]
        if window:
            windows.append(window)

    return windows


def build_field_logic_payload_from_contexts(field_name: str, contexts: list[dict]) -> dict | None:
    """
    说明：build_field_logic_payload_from_contexts 函数，处理当前模块的对应业务步骤。
    """
    field = (field_name or "").upper()
    rules = []
    dependencies = []
    special_cases = []
    related_outputs = []

    for context in contexts or []:
        for window in extract_field_windows(context.get("content") or "", field):
            for raw_line in window:
                line = clean_markdown_line(raw_line)
                if not line or line.startswith("#") or line.startswith("```"):
                    continue

                upper_line = line.upper()
                if field in upper_line and len(line) <= len(field) + 20:
                    continue

                if any(flag in line for flag in ["从", "获取", "取", "设置", "生成", "计算", "等于", "相同", "格式化", "匹配"]):
                    append_unique(rules, line)

                if any(flag in line for flag in ["df_", "字段", "列", "unit", "test", "依赖", "基于", "根据", "对应测试"]):
                    append_unique(dependencies, line)

                if any(flag in line for flag in ["若", "如果", "否则", "失败", "为空", "清空", "未显式"]):
                    append_unique(special_cases, line)

                other_fields = [
                    token for token in re.findall(r"\b[A-Z][A-Z0-9_]{2,}\b", upper_line)
                    if token != field
                ]
                if other_fields and any(flag in line for flag in ["相同", "相关", "输出", "与"]):
                    append_unique(related_outputs, line)

    payload = {
        "field_name": field or None,
        "calculation_rules": rules or None,
        "dependencies": dependencies or None,
        "special_cases": special_cases or None,
        "related_outputs": related_outputs or None,
    }
    return payload if has_substantive_field_logic(payload) else None
