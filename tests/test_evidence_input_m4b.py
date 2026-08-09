from __future__ import annotations

from uuid import uuid4

import pytest

from packages.database.models import EvidenceClaimType
from packages.evidence.domain import validate_extraction_data
from packages.evidence.errors import EvidenceValidationError
from packages.evidence.input_builder import EvidenceInputBuilder
from tests.m4b_helpers import create_event_context


@pytest.mark.usefixtures("clean_database")
async def test_input_builder_is_deterministic_bounded_and_excludes_raw_payload(db_session) -> None:  # type: ignore[no-untyped-def]
    event, signals = await create_event_context(
        db_session,
        texts=["A" * 20, "B" * 20, "C" * 20],
    )
    builder = EvidenceInputBuilder()
    first = await builder.build(
        event_id=event.id,
        max_signals=2,
        max_chars_per_signal=10,
        max_total_chars=15,
    )
    second = await builder.build(
        event_id=event.id,
        max_signals=2,
        max_chars_per_signal=10,
        max_total_chars=15,
    )
    assert [item.signal_id for item in first.signals] == [signals[0].id, signals[1].id]
    assert first.character_count <= 15
    assert first.input_hash == second.input_hash
    assert first.truncated is True
    prompt = "\n".join(message.content for message in first.messages())
    assert "raw_payload" not in prompt
    assert "raw_only" not in prompt
    assert "secret-that-must-not-enter-evidence" not in prompt


@pytest.mark.usefixtures("clean_database")
async def test_explicit_signal_from_another_event_is_rejected(db_session) -> None:  # type: ignore[no-untyped-def]
    event, _ = await create_event_context(db_session, texts=["目标事件来源"])
    _other_event, other_signals = await create_event_context(db_session, texts=["其他事件来源"])
    with pytest.raises(EvidenceValidationError):
        await EvidenceInputBuilder().build(
            event_id=event.id,
            signal_ids=[other_signals[0].id],
        )


def test_business_validation_supports_all_claim_types_and_rejects_bad_sources() -> None:
    support_id = uuid4()
    contradiction_id = uuid4()
    outside_id = uuid4()
    data = {
        "claims": [
            {
                "text": "单来源事实",
                "type": "fact",
                "supporting_signal_ids": [str(support_id)],
                "contradicting_signal_ids": [],
                "confidence": 0.5,
            },
            {
                "text": "指控",
                "type": "allegation",
                "supporting_signal_ids": [str(support_id)],
                "contradicting_signal_ids": [str(contradiction_id)],
                "confidence": 0.4,
            },
            {
                "text": "观点",
                "type": "opinion",
                "supporting_signal_ids": [str(support_id)],
                "contradicting_signal_ids": [],
                "confidence": None,
            },
            {
                "text": "预测",
                "type": "forecast",
                "supporting_signal_ids": [str(support_id)],
                "contradicting_signal_ids": [],
                "confidence": 0.3,
            },
            {
                "text": "无来源",
                "type": "fact",
                "supporting_signal_ids": [],
                "contradicting_signal_ids": [],
                "confidence": 0.3,
            },
            {
                "text": "事件外来源",
                "type": "fact",
                "supporting_signal_ids": [str(outside_id)],
                "contradicting_signal_ids": [],
                "confidence": 0.3,
            },
        ],
        "unknowns": [{"text": "仍不知道什么"}],
    }
    result = validate_extraction_data(
        data,
        allowed_signal_ids={support_id, contradiction_id},
    )
    assert {item.claim_type for item in result.claims} == {
        EvidenceClaimType.FACT,
        EvidenceClaimType.ALLEGATION,
        EvidenceClaimType.OPINION,
        EvidenceClaimType.FORECAST,
    }
    assert result.invalid_codes == ("UNSUPPORTED_CLAIM", "SIGNAL_NOT_IN_EVENT")
    assert [item.text for item in result.unknowns] == ["仍不知道什么"]
