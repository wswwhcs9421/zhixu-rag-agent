"""Offline dataset verification and opt-in retrieval measurement; never imports documents."""
from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from .build_sources import ROOT, normalized


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_questions():
    return [json.loads(line) for line in (ROOT / "questions.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate():
    from pypdf import PdfReader

    sources, questions = read_json(ROOT / "sources.json"), load_questions()
    meta, articles = read_json(ROOT / "metadata.json"), read_json(ROOT / "articles.json")
    source_map = {s["source_id"]: s for s in sources}
    article_map = {(a["source_id"], a["article"]): a for a in articles}
    require(len(sources) == len(source_map) == 10, "Expected ten unique sources")
    require(len(questions) == len({q["id"] for q in questions}) == 44, "Expected 44 unique questions")
    require(sum(q["answerable"] for q in questions) == 40, "Expected 40 answerable questions")
    require(digest(ROOT / "questions.jsonl") == meta["questions_sha256"], "Question hash mismatch")
    raw_path = ROOT / "sources_raw/财政部_企业内部控制应用指引_官方原文.pdf"
    raw_sha = digest(raw_path)
    pages = [normalized(re.sub(r"(?m)^\s*\d+\s*$", "", p.extract_text() or "")) for p in PdfReader(raw_path).pages]
    require(len(pages) == 83, "Original PDF page count changed")
    corpora = {}
    for source in sources:
        path = ROOT / source["path"]
        require(digest(path) == source["corpus_sha256"], f"Corpus hash mismatch: {path.name}")
        require(raw_sha == source["original_sha256"], "Original PDF hash mismatch")
        text = path.read_text(encoding="utf-8")
        corpora[source["source_id"]] = text
        selected = [a for a in articles if a["source_id"] == source["source_id"]]
        require(len(selected) == source["article_count"], "Article count mismatch")
        for article in selected:
            require(article["text"] in text, "Article not preserved in corpus")
            original = "".join(pages[p - 1] for p in article["pdf_pages"])
            require(article["text"] in original, "Article not found in original PDF")
    evidence_count, cross_document = 0, 0
    for q in questions:
        require(bool(q["expected_answer"]) and bool(q["required_points"]), "Missing answer/rubric")
        evidence = q["evidence"]
        require(bool(evidence) == q["answerable"], "Evidence/answerability mismatch")
        require(set(q["expected_source_ids"]) == {e["source_id"] for e in evidence}, "Source IDs mismatch")
        cross_document += len(q["expected_source_ids"]) > 1
        for e in evidence:
            corpus = corpora[e["source_id"]]
            require(source_map[e["source_id"]]["filename"] == e["filename"], "Evidence filename mismatch")
            require(corpus[e["corpus_char_start"]:e["corpus_char_end"]] == e["quote"], "Evidence offset mismatch")
            require(e["quote"] in article_map[e["source_id"], e["article"]]["text"], "Wrong article attribution")
            require(e["quote"] in "".join(pages[p - 1] for p in e["pdf_pages"]), "Wrong original PDF page attribution")
            evidence_count += 1
    require(cross_document == 4, "Expected four cross-document cases")
    with zipfile.ZipFile(ROOT / "仅上传知识库_10份制度资料.zip") as archive:
        require(sorted(archive.namelist()) == sorted(s["filename"] for s in sources), "ZIP must contain only corpus")
        for source in sources:
            require(archive.read(source["filename"]) == (ROOT / source["path"]).read_bytes(), "ZIP content mismatch")
    return {"status": "passed", "documents": 10, "articles": len(articles), "questions": 44,
            "answerable": 40, "unanswerable": 4, "cross_document": cross_document,
            "evidence_quotes_checked": evidence_count, "questions_sha256": meta["questions_sha256"],
            "original_pdf_sha256": raw_sha, "live_rag_measured": False}


def score_question(question, results, k):
    """Exact normalized quote coverage in correct documents; no answer-quality claim."""
    evidence = question["evidence"]
    if not question["answerable"]:
        return None
    top = results[:k]
    covered = [any(r.get("filename") == e["filename"] and normalized(e["quote"]) in normalized(r.get("content", ""))
                   for r in top) for e in evidence]
    return {"document_hit": any(r.get("filename") in {e["filename"] for e in evidence} for r in top),
            "all_evidence_hit": all(covered), "evidence_recall": sum(covered) / len(covered)}


def summarize(questions, rows):
    by_id = {row["id"]: row for row in rows}
    positive = [q for q in questions if q["answerable"]]
    require(bool(positive), "No answerable questions")
    metrics = {}
    errors = []
    for q in positive:
        row = by_id.get(q["id"])
        if row is None or row.get("error"):
            errors.append(q["id"])
    for k in (1, 3, 5):
        scores = [score_question(q, [] if by_id.get(q["id"], {}).get("error") else by_id.get(q["id"], {}).get("results", []), k)
                  for q in positive]
        metrics[f"at_{k}"] = {key: sum(s[key] for s in scores) / len(positive)
                              for key in ("document_hit", "all_evidence_hit", "evidence_recall")}
    return {"answerable_denominator": len(positive), "unanswerable_excluded": len(questions) - len(positive),
            "failed_or_missing_question_ids": errors, "retrieval": metrics,
            "answer_accuracy": None, "refusal_accuracy": None,
            "note": "Quote-based retrieval only. Answers and refusal require separate human review."}


def collect(url, username):
    import httpx

    questions, sources = load_questions(), read_json(ROOT / "sources.json")
    password = getpass.getpass("Login password (not saved): ")
    with httpx.Client(base_url=url.rstrip("/"), timeout=120) as client:
        response = client.post("/api/auth/login", json={"username": username, "password": password})
        del password
        response.raise_for_status()
        overview_response = client.get("/api/overview")
        overview_response.raise_for_status()
        overview = overview_response.json()
        ids, mapping = [], {}
        for source in sources:
            matches = [d for d in overview["documents"] if d["filename"] == source["filename"]]
            require(len(matches) == 1, f"Missing or duplicate corpus file: {source['filename']}")
            doc = matches[0]
            require(doc["status"] == "ready" and doc["chunk_count"] > 0 and doc["chunk_count"] == doc["vector_count"],
                    f"Document not completely indexed: {source['filename']}")
            # Check indexed chunks, not just filenames, against the frozen corpus.
            response = client.get(f"/api/documents/{doc['id']}/chunks")
            response.raise_for_status()
            chunks = response.json()
            corpus = normalized((ROOT / source["path"]).read_text(encoding="utf-8"))
            require(len(chunks) == doc["chunk_count"] and all(normalized(c["content"]) in corpus for c in chunks),
                    f"Indexed corpus changed: {source['filename']}")
            relevant = [e for q in questions for e in q["evidence"] if e["source_id"] == source["source_id"]]
            require(all(any(normalized(e["quote"]) in normalized(c["content"]) for c in chunks) for e in relevant),
                    f"Evidence missing from chunks: {source['filename']}")
            ids.append(doc["id"])
            mapping[source["source_id"]] = {"document_id": doc["id"], "chunks": chunks}
        rows = []
        for number, q in enumerate(questions, 1):
            row = {"id": q["id"], "question": q["question"], "results": [], "error": None,
                   "actual_answer": None, "answer_correct": None, "refusal_correct": None}
            try:
                response = client.post("/api/search", json={"query": q["question"], "document_ids": ids})
                response.raise_for_status()
                row["results"] = response.json()["results"]
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                # Do not save request payloads, cookies or credentials in error messages.
                row["error"] = type(exc).__name__
            rows.append(row)
            print(f"{number}/{len(questions)} {q['id']}: {'error' if row['error'] else 'ok'}", file=sys.stderr)
    return {"dataset": read_json(ROOT / "metadata.json"), "started_from_corpus": mapping,
            "models": overview["models"], "rows": rows, "metrics": summarize(questions, rows),
            "measurement": "direct /api/search retrieval, not multi-step agent or answer evaluation"}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["validate", "retrieval"], nargs="?", default="validate")
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.mode == "retrieval":
        require(args.output is not None, "retrieval requires --output with a new result filename")
    if args.output:
        require(not args.output.exists(), "Output exists; choose a new file to preserve earlier results")
    report = validate()
    if args.mode == "retrieval":
        report = collect(args.url, args.username)
    report["recorded_at"] = datetime.now(timezone.utc).isoformat()
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
    print(json.dumps(report.get("metrics", report), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
