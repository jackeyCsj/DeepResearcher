from types import SimpleNamespace

from client.agents.researcher import Researcher
from client.tools.base_tool import BaseTool, ToolParameter


class FakeTool(BaseTool):
    def __init__(self):
        super().__init__("search", "Search sources", [ToolParameter(name="query", type="string", description="Query")])

    def run_tool(self, parameters):
        return f"Results for: {parameters['query']}"


class FakeContextBuilder:
    def compress_old_rounds(self, *_args, **_kwargs):
        return None

    def build_context(self, system_prompt, history):
        return [{"role": "system", "content": system_prompt}] + [item.to_dict() for item in history]


class FakeLLM:
    model = "fake-model"

    def __init__(self):
        self.responses = [
            SimpleNamespace(
                tool_calls=[
                    SimpleNamespace(
                        id="call-1",
                        function=SimpleNamespace(name="search", arguments='{"query":"DeepJSCC"}'),
                        model_dump=lambda: {
                            "id": "call-1",
                            "type": "function",
                            "function": {"name": "search", "arguments": '{"query":"DeepJSCC"}'},
                        },
                    )
                ],
                content="",
            ),
            SimpleNamespace(tool_calls=None, content="DeepJSCC uses learned semantic encoding [1]."),
            SimpleNamespace(tool_calls=None, content="## Findings\nDeepJSCC uses learned semantic encoding [1]."),
        ]

    def invoke(self, **_kwargs):
        return self.responses.pop(0)


def test_researcher_preserves_tool_calls_and_returns_for_chat_history():
    researcher = Researcher(
        name="R-1",
        llm=FakeLLM(),
        context_builder=FakeContextBuilder(),
        tool_list=[FakeTool()],
        max_steps=2,
    )

    note, counts = researcher.run("Explain DeepJSCC")

    assert "DeepJSCC uses learned semantic encoding" in note
    assert counts == {"search": 1}
    assert researcher.get_research_trace() == [
        {
            "tool": "search",
            "arguments": {"query": "DeepJSCC"},
            "raw_result": "Results for: DeepJSCC",
            "result": "Results for: DeepJSCC",
        }
    ]
