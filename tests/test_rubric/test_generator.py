import pytest

from deep_research.models.evidence import EvidenceBase
from deep_research.models.rubric import CriterionKind, CriterionStatus, Rubric
from deep_research.models.topic import TaskContext, TopicSpec
from deep_research.rubric.generator import RubricGenerator


class FailingLLM:
    async def generate(self, *args, **kwargs):
        raise ValueError("invalid JSON")


@pytest.mark.asyncio
async def test_persistent_rubric_uses_fallback_when_json_is_invalid() -> None:
    generator = RubricGenerator(FailingLLM())
    context = TaskContext(
        topic=TopicSpec(
            query="Memory price research",
            core_topic="Memory price research",
        )
    )

    rubric = await generator.init_persistent(context)

    assert len(rubric.criteria) == 3
    assert all(
        criterion.status == CriterionStatus.UNKNOWN
        for criterion in rubric.criteria
    )
    assert {
        criterion.kind for criterion in rubric.criteria
    } >= {
        CriterionKind.SOURCE_CREDIBILITY,
        CriterionKind.QUANTITATIVE,
    }


@pytest.mark.asyncio
async def test_ephemeral_rubric_uses_conservative_fallback() -> None:
    generator = RubricGenerator(FailingLLM())

    rubric = await generator.update_ephemeral(
        TaskContext().outline,
        EvidenceBase(),
    )

    assert isinstance(rubric, Rubric)
    assert rubric.criteria[0].status == CriterionStatus.OUTSTANDING
    assert rubric.criteria[0].kind == CriterionKind.COVERAGE
