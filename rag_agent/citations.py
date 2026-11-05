from __future__ import annotations

import re

from .providers import ProviderError


def number_citations(answer, citations, *, strict=True):
    """Number used sources by first appearance, without changing their snapshots."""
    sources = {source["id"]: source for source in citations}
    aliases = list(dict.fromkeys(re.findall(r"\[(S\d+)\]", answer)))
    if any(alias not in sources for alias in aliases):
        if strict:
            raise ProviderError("模型生成了不存在的来源编号，本次答案未发布，请重试。")
        # Keep incomplete legacy records intact; never assign an unknown reference
        # to a different source while displaying historical evidence.
        return answer, citations
    mapping = {alias: f"S{index}" for index, alias in enumerate(aliases, 1)}
    answer = re.sub(r"\[(S\d+)\]", lambda match: f"[{mapping[match[1]]}]", answer)
    return answer, [{**sources[alias], "id": mapping[alias]} for alias in aliases]
