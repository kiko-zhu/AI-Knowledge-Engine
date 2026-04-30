from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# 数据库地址（先用 sqlite）
DATABASE_URL = "sqlite:///./test.db"

# 创建引擎
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}  # sqlite必须
)

# 创建 Session 工厂
SessionLocal = sessionmaker(
    autocommit=False,       # 不使用自动提交，需要手动调用 commit()
    autoflush=False,        # 不自动刷新（查询前不会自动将待提交的更改同步到数据库）
    bind=engine             # 绑定引擎
)

# Base（给 model 继承）
Base = declarative_base()


# 依赖注入用的函数
def get_db():
    """
    说明：get_db 函数，处理当前模块的对应业务步骤。
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()