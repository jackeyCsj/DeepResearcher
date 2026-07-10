from types import SimpleNamespace

import pytest

from deep_research.models.rubric import Criterion
from deep_research.rubric.generator import CriterionList
from deep_research.utils.llm_client import LLMClient


class FakeCompletions:
    def __init__(self) -> None:
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        content = (
            '{"criteria":[{"name":"source","guidance":"Use "quoted" evidence"}]}'
            if self.calls == 1
            else '{"criteria":[{"name":"source","guidance":"Use quoted evidence"}]}'
        )
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(content=content),
                )
            ]
        )


@pytest.mark.asyncio
async def test_generate_repairs_invalid_structured_json_once() -> None:
    client = LLMClient(
        api_key="test",
        base_url="https://example.invalid/v1",
        model="deepseek-chat",
    )
    completions = FakeCompletions()
    client._client = SimpleNamespace(
        chat=SimpleNamespace(completions=completions)
    )

    result = await client.generate(
        "Generate criteria",
        response_model=CriterionList,
    )

    assert completions.calls == 2
    assert isinstance(result.criteria[0], Criterion)
    assert result.criteria[0].guidance == "Use quoted evidence"
