from ..base import LLMClient


def answer_report_question(llm: LLMClient, question: str, sources: list[dict[str, str]]) -> str:
    if not sources:
        return "在当前报告和你的资料库中没有检索到足够依据来回答这个问题。你可以指出希望补查的方向，我会据此开展补充研究。"

    source_text = "\n\n".join(
        f"[{index}] {source['title']} ({source['file_id']})\n{source['excerpt']}"
        for index, source in enumerate(sources, 1)
    )
    response = llm.invoke(
        messages=[
            {
                "role": "system",
                "content": (
                    "根据提供的检索片段回答用户问题。只陈述片段能支持的事实；每个关键事实都用对应的方括号编号引用，"
                    "例如 [1]。证据不足时明确说明，不要推测，也不要自动启动研究。使用用户提问的语言。"
                ),
            },
            {
                "role": "user",
                "content": f"<question>\n{question}\n</question>\n\n<sources>\n{source_text}\n</sources>",
            },
        ],
        temperature=0,
        tag="report_qa",
    )
    return response.content
