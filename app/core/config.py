import os
from pydantic_settings import BaseSettings


BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

class Settings(BaseSettings):
    """
    说明：Settings 类，封装当前模块的数据结构或业务逻辑。
    """
    host: str = "10.21.0.150"
    port: int = 8001
    db_url: str = f"sqlite:///{os.path.join(BASE_DIR, 'test.db')}"
    llm_api_key: str = "sk-8c361a8fb25e4dbc9640a87c92183521"
    llm_base_url: str = "https://api.deepseek.com"
    # llm_model: str = "deepseek-chat"
    llm_model: str = "deepseek-v4-flash"
    send_code_root: str = r"D:\Project_text\send_code_api\info\projects\domain_lib"

    class Config:
        """
        说明：Config 类，封装当前模块的数据结构或业务逻辑。
        """
        env_file = ".env"

settings = Settings()
