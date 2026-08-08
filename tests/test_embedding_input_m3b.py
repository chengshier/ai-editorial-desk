from uuid import uuid4

from packages.database.models import RawSignalRecord
from packages.embeddings.input_builder import (
    SIGNAL_TEXT_INPUT_SCHEMA_VERSION,
    EmbeddingInputBuilder,
)


def _signal(*, title: str | None, text: str | None) -> RawSignalRecord:
    return RawSignalRecord(id=uuid4(), title=title, text=text)


def test_embedding_input_builder_title_and_text_is_deterministic() -> None:
    builder = EmbeddingInputBuilder()
    signal = _signal(title="  标题\n 一  ", text=" 正文\t内容 ")

    first = builder.build(signal)
    second = builder.build(signal)

    assert first is not None
    assert second == first
    assert first.text == "title: 标题 一\ntext: 正文 内容"
    assert first.input_schema_version == SIGNAL_TEXT_INPUT_SCHEMA_VERSION
    assert len(first.input_hash) == 64


def test_embedding_input_builder_title_only() -> None:
    result = EmbeddingInputBuilder().build(_signal(title=" 标题 ", text=None))
    assert result is not None
    assert result.text == "title: 标题"


def test_embedding_input_builder_text_only() -> None:
    result = EmbeddingInputBuilder().build(_signal(title=None, text=" 正文 "))
    assert result is not None
    assert result.text == "text: 正文"


def test_embedding_input_builder_empty_and_whitespace_returns_none() -> None:
    builder = EmbeddingInputBuilder()
    assert builder.build(_signal(title=None, text=None)) is None
    assert builder.build(_signal(title=" \n\t ", text="   ")) is None


def test_embedding_input_hash_changes_only_when_normalized_semantics_change() -> None:
    builder = EmbeddingInputBuilder()
    first = builder.build(_signal(title="A  B", text="C\nD"))
    normalized_equivalent = builder.build(_signal(title=" A B ", text=" C D "))
    changed = builder.build(_signal(title="A B", text="C E"))

    assert first is not None and normalized_equivalent is not None and changed is not None
    assert first.input_hash == normalized_equivalent.input_hash
    assert first.input_hash != changed.input_hash
