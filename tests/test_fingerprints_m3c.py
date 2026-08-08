from uuid import uuid4

from packages.clustering.fingerprints import (
    FINGERPRINT_INPUT_SCHEMA_VERSION,
    SIGNAL_FINGERPRINT_VERSION,
    SIMHASH_ALGORITHM_VERSION,
    FingerprintInputBuilder,
    hamming_distance,
)
from packages.database.models import RawSignalRecord


def _signal(title: str | None, text: str | None) -> RawSignalRecord:
    return RawSignalRecord(id=uuid4(), title=title, text=text)


def test_fingerprint_versions_are_explicit() -> None:
    builder = FingerprintInputBuilder()
    assert builder.input_schema_version == FINGERPRINT_INPUT_SCHEMA_VERSION == "fingerprint-text-v1"
    assert builder.fingerprint_version == SIGNAL_FINGERPRINT_VERSION == "signal-fingerprint-v1"
    assert builder.simhash_algorithm_version == SIMHASH_ALGORITHM_VERSION == "simhash64-v1"


def test_fingerprint_is_deterministic_for_unicode_whitespace_and_punctuation() -> None:
    builder = FingerprintInputBuilder()
    left = builder.fingerprint(_signal("ＡＩ 编辑部", "暴雨\n导致   地铁停运！"))
    right = builder.fingerprint(_signal("ai 编辑部", "暴雨 导致 地铁停运！"))
    assert left is not None and right is not None
    assert left.input_hash == right.input_hash
    assert left.simhash == right.simhash
    assert hamming_distance(left.simhash, right.simhash) == 0


def test_chinese_light_rewrite_has_small_distance() -> None:
    builder = FingerprintInputBuilder()
    left = builder.fingerprint(
        _signal("暴雨导致地铁临时停运", "官方称三号线将在晚间恢复运营")
    )
    right = builder.fingerprint(
        _signal("暴雨导致地铁临时停运", "官方称三号线将在晚间恢复运营。最新")
    )
    unrelated = builder.fingerprint(
        _signal("本地球队夺得联赛冠军", "球迷在主场庆祝赛季冠军")
    )
    assert left is not None and right is not None and unrelated is not None
    assert hamming_distance(left.simhash, right.simhash) <= 4
    assert hamming_distance(left.simhash, unrelated.simhash) > 4


def test_english_is_not_dependent_on_case_or_spacing() -> None:
    builder = FingerprintInputBuilder()
    left = builder.fingerprint(
        _signal("Metro Line Closed", "Service resumes tonight after heavy rain")
    )
    right = builder.fingerprint(
        _signal("metro   line closed", "service resumes tonight after heavy rain")
    )
    assert left is not None and right is not None
    assert left.simhash == right.simhash


def test_empty_title_and_text_do_not_create_fake_fingerprint() -> None:
    assert FingerprintInputBuilder().fingerprint(_signal("  ", "\n\t")) is None
