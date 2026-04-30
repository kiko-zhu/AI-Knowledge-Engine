from abc import ABC, abstractmethod


class BaseParser(ABC):
    """
       所有解析器的基类
       """
    @abstractmethod
    def parse(self, file_path: str) -> str:
        """
                解析文件
                :param file_path: 文件路径
                :return: 解析后的文本内容
                """
        pass