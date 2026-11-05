"""Download the official original and extract ten complete guidelines, without gold answers.

This creates benchmark artifacts only; it never writes to the application's database.
"""
from __future__ import annotations

import hashlib
import json
import re
import urllib.request
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent
OFFICIAL_PAGE = "https://kjs.mof.gov.cn/zhengcefabu/201005/t20100504_291943.htm"
PDF_URL = "https://kjs.mof.gov.cn/zhengcefabu/201005/P020230421440664863663.pdf"
RETRIEVED_DATE = "2026-11-01"
SELECTED = {3: "人力资源", 6: "资金活动", 7: "采购业务", 8: "资产管理", 9: "销售业务",
            11: "工程项目", 12: "担保业务", 15: "全面预算", 16: "合同管理", 18: "信息系统"}


def normalized(text):
    return re.sub(r"\s+", "", text).replace("\u3000", "")


def build():
    raw_dir = ROOT / "sources_raw"
    corpus_dir = ROOT / "corpus"
    raw_dir.mkdir(exist_ok=True)
    corpus_dir.mkdir(exist_ok=True)
    raw_path = raw_dir / "财政部_企业内部控制应用指引_官方原文.pdf"
    if not raw_path.exists():
        request = urllib.request.Request(PDF_URL, headers={"User-Agent": "Enterprise-RAG-Benchmark/1.0"})
        with urllib.request.urlopen(request, timeout=45) as response:
            raw = response.read()
        if not raw.startswith(b"%PDF"):
            raise ValueError("Official source did not return a PDF")
        raw_path.write_bytes(raw)
    raw_sha = hashlib.sha256(raw_path.read_bytes()).hexdigest()
    reader = PdfReader(raw_path)
    pages = []
    for number, page in enumerate(reader.pages, 1):
        text = page.extract_text() or ""
        text = re.sub(r"(?m)^\s*\d+\s*$", "", text).strip()
        pages.append((number, text))
    # Retain a source-coordinate map before whitespace normalization.
    combined, intervals = "", []
    for page, text in pages:
        begin = len(combined)
        combined += text + "\n"
        intervals.append((begin, len(combined), page))
    headings = list(re.finditer(r"(?m)^\s*企业内部控制应用指引第\s*(\d+)\s*号\s*[—－-]+\s*([^\n]+)", combined))
    if len(headings) != 18:
        raise ValueError(f"Expected 18 guidelines, found {len(headings)}; inspect the original PDF")
    manifest, all_articles = [], []
    for index, heading in enumerate(headings):
        guideline = int(heading.group(1))
        if guideline not in SELECTED:
            continue
        end = headings[index + 1].start() if index + 1 < len(headings) else len(combined)
        section = combined[heading.end():end]
        source_id = f"D{len(manifest) + 1:02}"
        title = f"企业内部控制应用指引第{guideline}号——{SELECTED[guideline]}"
        article_matches = list(re.finditer(r"第[一二三四五六七八九十百]+条", section))
        # Only article headings start a line; avoid splitting cross-references.
        article_matches = [match for match in article_matches if not section[:match.start()].rsplit("\n", 1)[-1].strip()]
        source_articles = []
        for n, match in enumerate(article_matches):
            article_end = article_matches[n + 1].start() if n + 1 < len(article_matches) else len(section)
            body = section[match.end():article_end]
            # Chapter headings belong to structure, not to the previous article's evidence.
            body = re.split(r"\n\s*第[一二三四五六七八九十]+章", body)[0]
            body = normalized(body)
            begin_abs = heading.end() + match.start()
            end_abs = heading.end() + match.end() + len(section[match.end():article_end])
            article_pages = [p for a, b, p in intervals if a < end_abs and b > begin_abs]
            source_articles.append({"source_id": source_id, "article": match.group(), "text": body, "pdf_pages": article_pages})
        if not source_articles:
            raise ValueError(f"No articles extracted for {title}")
        file_name = f"{source_id}_{SELECTED[guideline]}.md"
        body = f"# {title}\n\n来源：财政部《企业内部控制应用指引》，财会〔2010〕11号配套指引。\n"
        body += f"官方发布页：{OFFICIAL_PAGE}\n\n官方 PDF：{PDF_URL}\n\n"
        body += "版本说明：2010 年发布文本的固定测试快照，仅用于本测试集，不代表任何特定公司的现行制度。\n\n"
        for article in source_articles:
            body += f"## {article['article']}（官方 PDF 第 {', '.join(map(str, article['pdf_pages']))} 页）\n\n{article['text']}\n\n"
        (corpus_dir / file_name).write_text(body, encoding="utf-8", newline="\n")
        doc_pages = [p for a, b, p in intervals if a < end and b > heading.start()]
        manifest.append({"source_id": source_id, "title": title, "topic": SELECTED[guideline],
                         "guideline_number": guideline, "filename": file_name, "path": f"corpus/{file_name}",
                         "publisher": "中华人民共和国财政部", "publication_reference": "财会〔2010〕11号",
                         "version": "2010年发布文本", "retrieved_date": RETRIEVED_DATE,
                         "url": PDF_URL, "landing_page": OFFICIAL_PAGE, "pdf_pages": doc_pages,
                         "original_sha256": raw_sha, "corpus_sha256": hashlib.sha256(body.encode()).hexdigest(),
                         "article_count": len(source_articles), "extraction": "pypdf; remove page-number-only lines and normalize whitespace; retain all articles in the selected guideline"})
        all_articles.extend(source_articles)
    (ROOT / "sources.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    (ROOT / "articles.json").write_text(json.dumps(all_articles, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return {"documents": len(manifest), "articles": len(all_articles), "original_pdf_pages": len(reader.pages), "original_sha256": raw_sha}


if __name__ == "__main__":
    print(json.dumps(build(), ensure_ascii=False))
