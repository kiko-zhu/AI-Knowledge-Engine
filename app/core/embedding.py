from sentence_transformers import SentenceTransformer


# 模型只加载一次（全局）
model = SentenceTransformer("BAAI/bge-base-zh")

def get_embedding(text: str):
    """
    说明：get_embedding 函数，处理当前模块的对应业务步骤。
    """
    return model.encode(text).tolist()
