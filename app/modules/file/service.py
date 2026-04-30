"""
只负责存储/读取
"""

import os

class FileService:
    """
    说明：FileService 类，封装当前模块的数据结构或业务逻辑。
    """

    UPLOAD_DIR = "uploads"

    @classmethod
    def save_file(cls, file):
        """
        保存上传的文件。
        """
        os.makedirs(cls.UPLOAD_DIR, exist_ok=True)

        file_path = os.path.join(cls.UPLOAD_DIR, file.filename)

        with open(file_path, "wb") as f:
            f.write(file.file.read())

        return {
            "file_name": file.filename,
            "file_path": file_path
        }