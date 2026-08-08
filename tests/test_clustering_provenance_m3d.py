from packages.clustering.provenance import AssignmentProvenanceService
from packages.clustering.services import ClusterOutcomeStatus
from tests.m3c_helpers import auto_cluster, create_m3c_signal, create_source


async def test_standard_auto_create_and_attach_have_resolvable_algorithm_provenance(
    db_session,  # type: ignore[no-untyped-def]
) -> None:
    source = await create_source(db_session)
    first = await create_m3c_signal(
        db_session,
        source,
        external_id="provenance-a",
        title="同一事件",
        text="相同正文",
        url="https://example.com/provenance/a",
    )
    second = await create_m3c_signal(
        db_session,
        source,
        external_id="provenance-b",
        title="同一事件",
        text="相同正文",
        url="https://example.com/provenance/b",
    )

    created = await auto_cluster(db_session, first.id)
    attached = await auto_cluster(db_session, second.id)
    assert created.status is ClusterOutcomeStatus.CREATED_EVENT
    assert attached.status is ClusterOutcomeStatus.ATTACHED
    assert created.event_id == attached.event_id
    assert created.event_id is not None

    async with db_session.begin():
        resolver = AssignmentProvenanceService(db_session)
        first_provenance = await resolver.current(
            event_id=created.event_id,
            signal_id=first.id,
        )
        second_provenance = await resolver.current(
            event_id=created.event_id,
            signal_id=second.id,
        )

    assert first_provenance is not None
    assert first_provenance.source == "configuration_change_log"
    assert first_provenance.action == "cluster_create_event"
    assert first_provenance.algorithm_version == "event-match-v1"
    assert first_provenance.audit_log_id is not None

    assert second_provenance is not None
    assert second_provenance.source == "configuration_change_log"
    assert second_provenance.action == "cluster_attach_signal"
    assert second_provenance.algorithm_version == "event-match-v1"
    assert second_provenance.audit_log_id is not None
    assert second_provenance.evidence["match_decision"] == "exact_duplicate"
    assert second_provenance.evidence["attached_by"] == "rule"
