from evaluation.enterprise_v1.evaluate import load_questions, score_question, summarize, validate


def sample_question(answerable=True):
    return {"id": "Q1", "answerable": answerable,
            "evidence": [{"filename": "a.md", "quote": "先调整预算"},
                         {"filename": "b.md", "quote": "审批后办理请购"}] if answerable else []}


def test_document_hit_does_not_imply_evidence_hit():
    score = score_question(sample_question(), [{"filename": "a.md", "content": "一般预算原则"}], 5)
    assert score == {"document_hit": True, "all_evidence_hit": False, "evidence_recall": 0}


def test_cross_document_requires_all_evidence_and_correct_rank():
    results = [{"filename": "a.md", "content": "应先调整预算。"},
               {"filename": "b.md", "content": "审批后办理请购。"}]
    assert score_question(sample_question(), results, 1)["evidence_recall"] == 0.5
    assert not score_question(sample_question(), results, 1)["all_evidence_hit"]
    assert score_question(sample_question(), results, 3)["all_evidence_hit"]


def test_wrong_source_quote_does_not_count():
    result = [{"filename": "unrelated.md", "content": "先调整预算，审批后办理请购"}]
    assert score_question(sample_question(), result, 5)["evidence_recall"] == 0


def test_normalized_whitespace_preserves_evidence_match():
    results = [{"filename": "a.md", "content": "先 调整\n预算"},
               {"filename": "b.md", "content": "审批后 办理请购"}]
    assert score_question(sample_question(), results, 5)["all_evidence_hit"]


def test_negatives_excluded_and_errors_kept_in_denominator():
    q1 = sample_question()
    q2 = {**q1, "id": "Q2"}
    negative = {**sample_question(False), "id": "Q3"}
    rows = [{"id": "Q1", "results": [{"filename": "a.md", "content": "先调整预算"},
                                      {"filename": "b.md", "content": "审批后办理请购"}]},
            {"id": "Q2", "error": "HTTPStatusError", "results": []}]
    metrics = summarize([q1, q2, negative], rows)
    assert metrics["answerable_denominator"] == 2
    assert metrics["unanswerable_excluded"] == 1
    assert metrics["failed_or_missing_question_ids"] == ["Q2"]
    assert metrics["retrieval"]["at_5"]["all_evidence_hit"] == 0.5
    assert metrics["answer_accuracy"] is None
    assert score_question(negative, [], 5) is None


def test_missing_result_counts_as_failure():
    metrics = summarize([sample_question()], [])
    assert metrics["retrieval"]["at_5"]["document_hit"] == 0
    assert metrics["failed_or_missing_question_ids"] == ["Q1"]


def test_frozen_dataset_integrity_and_default_chunk_coverage():
    import json
    from evaluation.enterprise_v1.build_sources import ROOT, normalized
    from rag_agent.documents import parse_document, split_pages

    report = validate()
    assert report["questions"] == 44
    assert report["evidence_quotes_checked"] == 68
    assert report["live_rag_measured"] is False
    by_filename = {}
    for path in (ROOT / "corpus").glob("*.md"):
        by_filename[path.name] = split_pages(parse_document(path, path.name), 1000, 120)
    for question in load_questions():
        for evidence in question["evidence"]:
            assert any(normalized(evidence["quote"]) in normalized(chunk["content"])
                       for chunk in by_filename[evidence["filename"]]), evidence["evidence_id"]
    # Structural splitting must retain every complete source article, not just gold quotes.
    articles = json.loads((ROOT / "articles.json").read_text(encoding="utf-8"))
    for article in articles:
        chunks = next(v for filename, v in by_filename.items() if filename.startswith(article["source_id"] + "_"))
        matching = [c for c in chunks if article["text"] in normalized(c["content"])]
        assert len(matching) == 1, (article["source_id"], article["article"])
        assert article["article"] in matching[0]["section"]
