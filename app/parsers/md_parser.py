from app.parsers.base import BaseParser
from .utils import validate_file


class MarkdownParser(BaseParser):
    """
    说明：MarkdownParser 类，封装当前模块的数据结构或业务逻辑。
    """
    def parse(self, file_path: str) -> str:
        # 先校验
        """
        说明：parse 函数，处理当前模块的对应业务步骤。
        """
        validate_file(file_path)

        # 再解析
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # 可以简单处理一下（去掉多余空行）
        return content.strip()