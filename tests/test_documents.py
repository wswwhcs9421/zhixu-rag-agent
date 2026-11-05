import pytest
from pypdf import PdfWriter

from rag_agent.documents import document_topic, parse_document, split_pages


def test_chunks_retain_page_provenance_and_cover_content():
    page1 = "甲" * 900 + "。\n\n" + "乙" * 900
    pages = [{"text": page1, "page": 1}, {"text": "# 第二章\n\n这是第二页的内容。", "page": 2}]
    chunks = split_pages(pages, 1000, 120)
    assert len(chunks) >= 3
    assert all(0 < len(c["content"]) <= 1000 for c in chunks)
    assert "甲" * 800 in chunks[0]["content"]
    assert "乙" * 800 in chunks[1]["content"]
    assert chunks[-1]["page"] == 2
    assert chunks[-1]["section"] == "第二章"
    assert document_topic(pages, "fallback.md") == "第二章"


def test_scanned_or_empty_pdf_fails_with_actionable_message(tmp_path):
    path = tmp_path / "scan.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    writer.write(path)
    with pytest.raises(ValueError, match="OCR"):
        parse_document(path, "scan.pdf")


def test_text_encoding_and_binary_rejection(tmp_path):
    path = tmp_path / "text.txt"
    path.write_bytes("中文内容".encode("gb18030"))
    assert parse_document(path, "text.txt")[0]["text"] == "中文内容"
    path.write_bytes(b"binary\x00file")
    with pytest.raises(ValueError, match="文本"):
        parse_document(path, "text.txt")


def test_complete_articles_keep_conditions_exceptions_and_hierarchy():
    text = "# 采购制度\n\n第一章 请购\n\n第一条 部门应先审批。小额零星物资除外。\n第二条 预算外需求应先调整预算。"
    chunks = split_pages([{"text": text, "page": None}], 1000, 120)
    assert len(chunks) == 2
    assert "第一条 部门应先审批。小额零星物资除外。" in chunks[0]["content"]
    assert "第二条" not in chunks[0]["content"]
    assert "第一条" not in chunks[1]["content"]
    assert chunks[0]["section"] == "采购制度 / 第一章 请购 / 第一条"
    assert chunks[1]["section"] == "采购制度 / 第一章 请购 / 第二条"


def test_markdown_article_and_inline_cross_reference():
    text = "# 制度\n\n## 第六条\n\n应按第七条的规定审批。例外应保留。\n\n## 第七条\n\n不得越权。"
    chunks = split_pages([{"text": text, "page": None}], 1000, 120)
    assert len(chunks) == 2
    assert chunks[0]["section"] == "制度 / 第六条"
    assert "应按第七条的规定审批。例外应保留。" in chunks[0]["content"]


def test_oversized_article_splits_at_sentences_and_keeps_its_identity():
    sentences = [f"事项{i:02}应当遵守审批流程并保留相关记录，" + "需要完整审查。" * 4 for i in range(12)]
    text = "# 审批制度\n\n第一条 " + "".join(sentences) + "\n第二条 下一事项不得混入前条。"
    chunks = split_pages([{"text": text, "page": None}], 200, 60)
    first_article = [c for c in chunks if c["section"].endswith("第一条")]
    assert len(first_article) > 1
    assert all(0 < len(c["content"]) <= 200 for c in chunks)
    # Every sentence survives whole in at least one fragment.
    for sentence in "".join(sentences).split("。"):
        if sentence:
            assert any(sentence + "。" in c["content"] for c in first_article)
    assert all("第二条" not in c["content"] for c in first_article)
    assert "事项" not in chunks[-1]["content"].split("下一事项")[0]
    assert chunks[-1]["section"].endswith("第二条")


def test_article_can_continue_across_pdf_pages_with_start_page_provenance():
    pages = [{"text": "第一章 审批\n第一条 支出应按流程审批，", "page": 7},
             {"text": "其中紧急事项仍需保留凭证。\n第二条 不得越权。", "page": 8}]
    chunks = split_pages(pages, 1000, 120)
    assert len(chunks) == 2
    assert "支出应按流程审批，\n其中紧急事项仍需保留凭证。" in chunks[0]["content"]
    assert chunks[0]["page"] == 7
    assert chunks[1]["page"] == 8
    assert chunks[1]["section"] == "第一章 审批 / 第二条"


def test_markdown_subheadings_keep_parent_and_ignore_code_headings():
    text = "# 制度\n## 第一条\n审批原则。\n### 特殊情况\n保留例外。\n```text\n# 示例不是标题\n```\n## 第二条\n新的规定。"
    chunks = split_pages([{"text": text, "page": None}], 1000, 120)
    assert len(chunks) == 2
    assert chunks[0]["section"] == "制度 / 第一条"
    assert "### 特殊情况\n保留例外。" in chunks[0]["content"]
    assert "# 示例不是标题" in chunks[0]["content"]
    assert chunks[1]["section"] == "制度 / 第二条"


def test_general_markdown_sections_keep_their_hierarchy():
    text = "# 员工手册\n## 报销\n报销说明。\n### 住宿\n住宿要求。\n## 考勤\n考勤要求。"
    chunks = split_pages([{"text": text, "page": None}], 1000, 120)
    assert [c["section"] for c in chunks] == ["员工手册 / 报销", "员工手册 / 报销 / 住宿", "员工手册 / 考勤"]


def test_unstructured_text_keeps_paragraphs_and_empty_pages_do_not_hide_content():
    a, b, c = "甲" * 140 + "。", "乙" * 140 + "。", "丙" * 140 + "。"
    chunks = split_pages([{"text": "", "page": 1}, {"text": a + "\n\n" + b + "\n\n" + c, "page": 2}], 200, 40)
    assert all(len(x["content"]) <= 200 and x["page"] == 2 for x in chunks)
    assert all(any(paragraph in x["content"] for x in chunks) for paragraph in (a, b, c))


def test_long_text_without_boundaries_is_not_lost():
    text = "无标点正文" * 180
    chunks = split_pages([{"text": text, "page": None}], 200, 40)
    reconstructed = chunks[0]["content"]
    for chunk in chunks[1:]:
        assert reconstructed[-40:] == chunk["content"][:40]
        reconstructed += chunk["content"][40:]
    assert reconstructed == text


@pytest.mark.parametrize("size,overlap", [(0, 0), (100, -1), (100, 100)])
def test_invalid_split_parameters_fail(size, overlap):
    with pytest.raises(ValueError):
        split_pages([{"text": "内容", "page": None}], size, overlap)
