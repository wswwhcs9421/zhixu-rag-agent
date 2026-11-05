"""Save public enterprise policy examples for offline chunking regression checks.

Research fixtures only: does not import anything into the application's knowledge base.
"""
from __future__ import annotations

import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent
SOURCES = [
    ("gitlab_expenses", "GitLab Global Travel and Expense Policy", "https://handbook.gitlab.com/handbook/finance/expenses/", "finance/expenses.md", ["numeric_outline", "lists", "exceptions"]),
    ("gitlab_procurement", "GitLab Procurement", "https://handbook.gitlab.com/handbook/finance/procurement/", "finance/procurement/_index.md", ["alphanumeric_outline", "workflow", "lists"]),
    ("gitlab_faq", "GitLab Coupa FAQ", "https://handbook.gitlab.com/handbook/finance/procurement/coupa-faq/", "finance/procurement/coupa-faq.md", ["question_answer", "headings"]),
    ("gitlab_navan", "GitLab Navan Expense End Users Guide", "https://handbook.gitlab.com/handbook/business-technology/enterprise-applications/guides/navan-expense-guide/", "business-technology/enterprise-applications/guides/navan-expense-guide/_index.md", ["workflow", "ordered_lists", "headings"]),
    ("gitlab_leave", "GitLab Leave Types", "https://handbook.gitlab.com/handbook/people-group/time-off-and-absence/leave-types/", "people-group/time-off-and-absence/leave-types.md", ["eligibility", "exceptions", "headings"]),
    ("gitlab_benefits", "GitLab Benefits", "https://handbook.gitlab.com/handbook/total-rewards/benefits/", "total-rewards/benefits/_index.md", ["bullet_lists", "headings"]),
    ("basecamp_benefits", "37signals Benefits & Perks", "https://basecamp.com/handbook/benefits-and-perks", None, ["prose", "headings", "lists"]),
    ("basecamp_work", "37signals How We Work", "https://basecamp.com/handbook/how-we-work", None, ["prose", "headings"]),
]


class MarkdownText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.lists = [], []

    def handle_starttag(self, tag, attrs):
        if re.fullmatch("h[1-6]", tag):
            self.parts.append("\n\n" + "#" * int(tag[1]) + " ")
        elif tag in {"p", "div", "section", "blockquote"}:
            self.parts.append("\n\n")
        elif tag in {"ul", "ol"}:
            self.lists.append(0 if tag == "ol" else None)
            self.parts.append("\n")
        elif tag == "li":
            if self.lists and self.lists[-1] is not None:
                self.lists[-1] += 1
                marker = f"{self.lists[-1]}. "
            else:
                marker = "- "
            self.parts.append("\n" + "  " * max(0, len(self.lists) - 1) + marker)
        elif tag == "br":
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"ul", "ol"} and self.lists:
            self.lists.pop()
        if tag in {"p", "div", "section", "li"} or re.fullmatch("h[1-6]", tag):
            self.parts.append("\n")

    def handle_data(self, data):
        value = re.sub(r"\s+", " ", data)
        if value.strip():
            self.parts.append(value)


def collect():
    fixtures = ROOT / "public_sources"
    fixtures.mkdir(parents=True, exist_ok=True)
    manifest = []
    with httpx.Client(timeout=45, follow_redirects=True) as client:
        for source_id, title, page_url, raw_path, structures in SOURCES:
            output = fixtures / f"{source_id}.md"
            url = ("https://gitlab.com/gitlab-com/content-sites/handbook/-/raw/main/content/handbook/" + raw_path) if raw_path else page_url
            if not output.exists():
                if raw_path:
                    response = client.get(url)
                    response.raise_for_status()
                    text = response.text
                    if not text.startswith("---"):
                        raise ValueError(f"Expected Markdown source: {source_id}")
                    text = re.sub(r"\A---\s*\n.*?\n---\s*\n", "", text, count=1, flags=re.S)
                    text = f"# {title}\n\n" + text.strip() + "\n"
                else:
                    cached = ROOT / "research_raw" / f"{source_id}.html"
                    html = cached.read_text(encoding="utf-8") if cached.exists() else client.get(url).raise_for_status().text
                    main = re.search(r"<main\b[^>]*>(.*?)</main>", html, re.S)
                    if not main:
                        raise ValueError(f"Main content missing: {source_id}")
                    body = re.split(r"<h[1-6][^>]*>\s*37signals Employee Handbook", main.group(1), maxsplit=1)[0]
                    body = re.sub(r"<(script|style|nav)\b[^>]*>.*?</\1>", "", body, flags=re.S)
                    parser = MarkdownText()
                    parser.feed(body)
                    text = re.sub(r"\n{3,}", "\n\n", "".join(parser.parts)).strip() + "\n"
                output.write_text(text, encoding="utf-8", newline="\n")
            manifest.append({"id": source_id, "title": title, "page_url": page_url, "download_url": url,
                             "path": f"public_sources/{output.name}", "snapshot_date": "2026-11-02",
                             "sha256": hashlib.sha256(output.read_bytes()).hexdigest(), "structures": structures,
                             "conversion": "public Markdown with front matter removed and source title added" if raw_path else "HTML main body converted to Markdown; navigation removed"})
    (ROOT / "sources.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"Saved {len(manifest)} public policy examples")


if __name__ == "__main__":
    collect()
