import os


ALLOWED_EXTENSIONS = {".md"}


def validate_file(file_path: str):
    # 1. 文件是否存在
    """
    说明：validate_file 函数，处理当前模块的对应业务步骤。
    """
    if not os.path.exists(file_path):
        raise ValueError("文件不存在")

    # 2. 是否是文件（不是目录）
    if not os.path.isfile(file_path):
        raise ValueError("不是有效文件")

    # 3. 后缀校验
    _, ext = os.path.splitext(file_path)
    if ext.lower() not in ALLOWED_EXTENSIONS:
        raise ValueError(f"不支持的文件类型: {ext}")