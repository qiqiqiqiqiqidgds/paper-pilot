"""真实 e2e 验证: 用项目内的 LLMClient 调 MiniMax-M3 chat_json,
确认 <think> 标签剥离后 JSON 能正确 parse。消耗少量 token plan 配额。"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.services.llm_client import get_llm_client


async def main():
    client = get_llm_client()
    print(f"客户端初始化: model={client.model}, max_tokens_override={client.max_tokens_override}")

    # 真实调用: 让 M3 返回 JSON(必须带 <think> 标签才会暴露问题)
    messages = [
        {
            "role": "system",
            "content": "你是一个简洁的助手。用 JSON 回答,只输出 JSON,不要任何其他内容。",
        },
        {
            "role": "user",
            "content": '请返回: {"greeting": "你好", "topic": "MiniMax-M3 集成测试"}',
        },
    ]

    print("\n=== 调用 M3 chat_json ===")
    result = await client.chat_json(messages, max_tokens=200)
    print(f"✅ 解析成功! 返回 dict: {result}")
    print(f"   greeting = {result.get('greeting')!r}")
    print(f"   topic    = {result.get('topic')!r}")

    # 再调一次非 JSON 路径,看 chat() 行为
    print("\n=== 调用 M3 chat (非 JSON) ===")
    text = await client.chat(
        messages=[
            {"role": "user", "content": "用一句话回答: 1+1=?"},
        ],
        max_tokens=80,
    )
    print("✅ chat 返回文本(可能含 <think> 标签):")
    print(f"   {text!r}")
    has_think = "<think>" in text
    print(f"   包含 <think> 标签: {has_think} (chat 路径保留原内容,只有 chat_json 才剥离)")


if __name__ == "__main__":
    asyncio.run(main())
