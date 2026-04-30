from .md_parser import MarkdownParser


def get_parser(file_path: str):
    """
    说明：get_parser 函数，处理当前模块的对应业务步骤。
    """
    if file_path.endswith(".md"):
        return MarkdownParser()
    else:
        raise ValueError("暂不支持该文件类型")