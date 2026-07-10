from deep_research.models.rubric import (
    Criterion,
    CriterionKind,
    CriterionStatus,
    Rubric,
)


def test_structured_status_controls_gap_detection() -> None:
    sufficient = Rubric(
        criteria=[
            Criterion(
                guidance="Cross-source verification is sufficient.",
                kind=CriterionKind.SOURCE_CREDIBILITY,
                status=CriterionStatus.SUFFICIENT,
            )
        ]
    )
    outstanding = Rubric(
        criteria=[
            Criterion(
                guidance="Resolve contradictory market estimates.",
                kind=CriterionKind.CONFLICT,
                status=CriterionStatus.OUTSTANDING,
            )
        ]
    )

    assert sufficient.has_outstanding_gap() is False
    assert outstanding.has_outstanding_gap() is True
