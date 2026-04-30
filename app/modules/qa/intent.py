import re


CODE_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_])([A-Z][A-Z0-9_]{1,})(?![A-Za-z0-9_])")


def extract_target_domain_code(query: str) -> str | None:
    """
    从诸如“VS域”或“EX域”这样的中文域名问题中提取“SEND”域名代码。
    使用 ASCII 查找模式而非 \b ，因为中文后缀在 Python 正则表达式中属于单词字符，这可能会导致像“VSTPT字段”这样的匹配出现错误。
    """
    value = (query or "").upper()
    match = re.search(r"(?<![A-Z0-9_])([A-Z]{2})\s*域", value)
    if match:
        return match.group(1)

    match = re.search(r"(?<![A-Z0-9_])([A-Z]{2})(?![A-Z0-9_])", value)
    if match and "域" in value:
        return match.group(1)

    return None


def extract_field_tokens(query: str) -> list[str]:
    """
    说明：extract_field_tokens 函数，处理当前模块的对应业务步骤。
    """
    value = (query or "").strip().upper()
    domain_code = extract_target_domain_code(value)
    seen = []

    for token in CODE_TOKEN_RE.findall(value):
        if len(token) < 3:
            continue
        if domain_code and token == domain_code:
            continue
        if token not in seen:
            seen.append(token)

    return seen
