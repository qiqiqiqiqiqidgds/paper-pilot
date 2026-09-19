"""手动验证 LLM 配置加载 + _strip_think_tags 行为(不消耗 token plan)"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.config import settings

print("=== config 加载结果 ===")
print(f"  llm_api_key        = {settings.llm_api_key[:24] + '...' if settings.llm_api_key else 'EMPTY'}")
print(f"  llm_base_url       = {settings.llm_base_url}")
print(f"  llm_model          = {settings.llm_model}")
print(f"  llm_max_tokens     = {settings.llm_max_tokens}")
print(f"  llm_reasoning_split= {settings.llm_reasoning_split}")
print(f"  llm_reasoning_effort={settings.llm_reasoning_effort!r}")
print(f"  老 deepseek_api_key (向后兼容) = {'存在' if settings.deepseek_api_key else '空'}")

print()
print("=== _strip_think_tags 单元测试 ===")
from app.services.llm_client import _strip_think_tags

cases = [
    # (输入, 期望输出)——基于实测 MiniMax-M3 返回的 <think>...</think> 格式
    ("hello world", "hello world"),
    ("<think>x</think>hi", "hi"),
    ("<think>x</think><think>y</think>hi", "hi"),
    ("<think>跨\n行\n内容</think>正文", "正文"),
    ("<|think|>变体</think|>", "<|think|>变体</think|>"),  # MiniMax 实际不用,保留原样(没匹配上)
    ("<think>只思考</think>", "<think>只思考</think>"),  # 剥后为空, 兜底保留原文
    ("<think>a</think>残留<think>b", "残留<think>b"),  # 不匹配的尾部保留
    ("", ""),
]
ok = 0
for raw, expected in cases:
    got = _strip_think_tags(raw)
    mark = "OK " if got == expected else "FAIL"
    if got == expected:
        ok += 1
    print(f"  [{mark}] in={raw!r:50s} -> out={got!r:30s} (expected={expected!r})")
print(f"\n  {ok}/{len(cases)} passed")
