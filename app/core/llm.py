from openai import OpenAI
from app.core.config import settings

client = OpenAI(
    api_key=settings.llm_api_key,
    base_url=settings.llm_base_url
)


def summarize_markdown(content: str) -> str:
    """
    说明：summarize_markdown 函数，处理当前模块的对应业务步骤。
    """
    prompt = f"""
    你是一个文档解析助手。

    请严格返回 JSON，禁止输出任何解释、文字、markdown。

    格式如下：
    {{
      "summary": "一句话总结",
      "keywords": ["关键词"],
      "sections": [
        {{
          "title": "",
          "desc": ""
        }}
      ]
    }}

    文档内容：
    {content}
    """

    resp = client.chat.completions.create(
        model=settings.llm_model,
        messages=[
            {"role": "user", "content": prompt}
        ],
        temperature=0.3
    )

    return resp.choices[0].message.content




def chat(prompt: str):
    """
    说明：chat 函数，处理当前模块的对应业务步骤。
    """
    resp = client.chat.completions.create(
        model=settings.llm_model,
        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ],
        temperature=0.2
    )

    return resp.choices[0].message.content


def extract_knowledge_cards(content: str) -> str:
    """
    说明：extract_knowledge_cards 函数，处理当前模块的对应业务步骤。
    """
    prompt = f"""
    你是一个知识整理助手。

    请严格返回 JSON，禁止输出任何解释、文字、markdown。

    格式如下：
    {{
      "cards": [
        {{
          "title": "规则/主题名",
          "category": "例如：关键逻辑/输入输出/异常处理/字段规则",
          "summary": "一句话说明",
          "details": [
            "要点1",
            "要点2"
          ]
        }}
      ]
    }}

    要求：
    - 只提取文档里真正有价值的知识点
    - 控制在 3 到 8 张卡片
    - details 必须是简洁短句

    文档内容：
    {content}
    """

    resp = client.chat.completions.create(
        model=settings.llm_model,
        messages=[
            {"role": "user", "content": prompt}
        ],
        temperature=0.2
    )

    return resp.choices[0].message.content
