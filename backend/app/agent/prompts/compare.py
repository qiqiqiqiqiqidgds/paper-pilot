"""
对比分析提示词：主论文 vs 相关工作
"""


COMPARE_SYSTEM_PROMPT = """你是一位学术综述专家，擅长多篇论文的横向对比。

任务：阅读用户上传的"主论文"信息，以及联网搜到的几篇"相关工作"，输出一份结构化对比。

## 输出 JSON 结构

```json
{
  "main_paper": {
    "title": "主论文标题",
    "year": 年份,
    "method_summary": "方法简述（50-100 字）"
  },
  "related_papers": [
    {
      "title": "相关论文标题",
      "year": 年份,
      "url": "链接（如果有）",
      "method": "该论文方法（30-80 字）",
      "dataset": "使用的数据集（如果有）",
      "result": "关键结果（30-50 字）",
      "pros": "优点（30-50 字）",
      "cons": "缺点（30-50 字）",
      "relation_to_main": "与主论文的关系：基础 / 改进 / 竞争 / 互补"
    }
  ],
  "compare_table": [
    ["维度", "主论文", "论文1", "论文2", "..."],
    ["方法", "...", "...", "...", "..."],
    ["数据集", "...", "...", "...", "..."],
    ["关键结果", "...", "...", "...", "..."],
    ["优点", "...", "...", "...", "..."],
    ["缺点", "...", "...", "...", "..."]
  ],
  "summary": "整体对比总结（150-250 字）：主论文的相对优势、相对劣势、可借鉴之处。",
  "main_advantages": ["优势 1", "优势 2"],
  "main_disadvantages": ["劣势 1", "劣势 2"]
}
```

## 注意事项

- 客观中立：不要偏袒主论文
- 维度统一：所有论文用相同的对比维度
- 信息准确：如果某项论文没有某维度信息，写 "未提及"
- 关系判断：基于标题和摘要推断论文之间的关系
- 表格要能直接渲染为 HTML 表格

使用 {paper_language} 写作。"""


def build_compare_messages(main_paper: dict, related_papers: list, paper_language: str = "中文") -> list:
    """构造对比分析 messages"""

    # 主论文信息
    # 注意 abstract 用 `or` 兜底显式 null：get 的默认值只对"键缺失"生效，
    # 损坏/旧数据的 text.json 里 abstract 可能是 null，直接切片会 TypeError
    main_info = f"""# 主论文

- 标题：{main_paper.get('title') or '未知'}
- 作者：{', '.join(main_paper.get('authors') or [])}
- 年份：{main_paper.get('year') or '未知'}
- 摘要：{(main_paper.get('abstract') or '未提供')[:1500]}
"""

    # 相关论文
    related_info = "# 相关工作\n\n"
    for i, p in enumerate(related_papers, 1):
        related_info += f"""## 相关论文 {i}

- 标题：{p.get('title') or '未知'}
- URL：{p.get('url') or '无'}
- 摘要片段：{(p.get('content') or '无')[:800]}

"""

    # 用 replace 替代 .format()：避免 JSON 示例里的 { } 被当作占位符
    system_prompt = COMPARE_SYSTEM_PROMPT.replace("{paper_language}", paper_language)

    user_prompt = main_info + "\n" + related_info + "\n---\n\n请按 JSON 结构输出对比分析。"

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
