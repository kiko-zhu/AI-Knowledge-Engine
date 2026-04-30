from fastapi import APIRouter, File, UploadFile

from app.modules.file.service import FileService

file_router = APIRouter()


@file_router.post(
    "/upload",
    summary="上传原始文件",
    description="上传待解析的文档文件，后端保存文件后返回 file_name 和 file_path，供后续创建解析任务使用。"
)
def upload_file(
    file: UploadFile = File(
        ...,
        description="要上传的原始文档文件，例如 PDF、DOCX、XLSX、TXT。"
    )
):
    """
    说明：upload_file 函数，处理当前模块的对应业务步骤。
    """
    return FileService.save_file(file)

