import pytest

from rag_agent.citations import number_citations
from rag_agent.providers import ProviderError


def test_sources_follow_first_use_without_collisions_or_snapshot_mutation():
    sources = [{"id": f"S{i}", "ordinal": i + 5, "content": f"原文{i}"} for i in range(1, 5)]
    answer, citations = number_citations("先[S4]，再[S1]，重复[S4]，最后[S3]。", sources)
    assert answer == "先[S1]，再[S2]，重复[S1]，最后[S3]。"
    assert [c["id"] for c in citations] == ["S1", "S2", "S3"]
    assert [c["ordinal"] for c in citations] == [9, 6, 8]
    assert [c["content"] for c in citations] == ["原文4", "原文1", "原文3"]
    assert sources[3]["id"] == "S4"


def test_unknown_sources_are_rejected_before_numbering():
    sources = [{"id": "S3", "ordinal": 7}]
    with pytest.raises(ProviderError, match="不存在的来源"):
        number_citations("已知[S3]，伪造[S999]。", sources)
    # Incomplete historical records cannot be silently reassigned to other sources.
    assert number_citations("[S3][S1]", sources, strict=False) == ("[S3][S1]", sources)


def test_unused_sources_do_not_become_answer_citations():
    assert number_citations("证据不足。", [{"id": "S1"}]) == ("证据不足。", [])
