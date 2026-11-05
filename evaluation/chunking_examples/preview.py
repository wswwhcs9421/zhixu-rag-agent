"""Generate reviewable examples and an offline retention report, without model calls."""
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parents[1]
sys.path.insert(0, str(PROJECT))

from rag_agent.documents import split_pages  # noqa: E402


def retained_in_order(text, chunks):
    original = "".join(text.split())
    position = 0
    for character in "".join("".join(c["content"].split()) for c in chunks):
        if position < len(original) and character == original[position]:
            position += 1
    return position == len(original)


def section_excerpt(text, phrase):
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if phrase in line and line.startswith("#"))
    level = len(re.match(r"#+", lines[start]).group())
    end = next((i for i in range(start + 1, len(lines)) if re.match(r"#{1," + str(level) + r"}\s", lines[i])), len(lines))
    return "\n".join(lines[start:end]).strip()


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sources = json.loads((ROOT / "sources.json").read_text(encoding="utf-8"))
    public_reports, source_text = [], {}
    for source in sources:
        path = ROOT / source["path"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != source["sha256"]:
            raise ValueError(f"Source snapshot changed: {source['id']}")
        text = path.read_text(encoding="utf-8")
        source_text[source["id"]] = text
        chunks = split_pages([{"text": text, "page": None}], 1000, 120)
        if not retained_in_order(text, chunks) or not all(0 < len(c["content"]) <= 1000 for c in chunks):
            raise ValueError(f"Content retention/size check failed: {source['id']}")
        public_reports.append({"id": source["id"], "title": source["title"], "url": source["page_url"],
                               "sha256": source["sha256"], "characters": len(text), "chunks": len(chunks),
                               "min_chunk_chars": min(len(c["content"]) for c in chunks),
                               "max_chunk_chars": max(len(c["content"]) for c in chunks),
                               "original_nonwhitespace_text_retained_in_order": True})
    examples = [
        ("真实案例：GitLab 差旅政策数字标题（去除 Markdown 标记以模拟纯文本）",
         re.sub(r"(?m)^#{1,6}\s+", "", section_excerpt(source_text["gitlab_expenses"], "4.3 Missing Receipt Affidavit") + "\n\n" + section_excerpt(source_text["gitlab_expenses"], "4.4 Reimbursement Payout Timelines")), 1000, "gitlab_expenses"),
        ("真实案例：GitLab 采购 FAQ 问题与回答",
         section_excerpt(source_text["gitlab_faq"], "How do suppliers register for the CSP?"), 1000, "gitlab_faq"),
        ("真实案例：GitLab 采购混合编号",
         section_excerpt(source_text["gitlab_procurement"], "2.A."), 1000, "gitlab_procurement"),
        ("合成案例：中文层级与普通栏目",
         "星海公司费用报销管理办法\n一、适用范围\n适用于全体员工。\n二、审批要求\n预算外项目依授权审批。\n（一）普通费用\n按既定流程审批。\n（二）特殊费用\n另行提供证明。", 1000, None),
        ("合成案例：ISO 风格数字层级",
         "# 采购控制程序\n1.0 目的\n规范采购行为。\n2.0 范围\n本程序的适用对象。\n2.1 国内采购\n国内采购的要求。\n2.2 境外采购\n境外采购的要求。", 1000, None),
        ("合成案例：问答与长回答",
         "# 报销问答\n问：缺少发票怎么办？\n答：" + "应核对适用制度并补充合规证明材料，保留审核记录。" * 18 + "\n问：谁负责审批？\n答：依据本公司的有效授权表。", 240, None),
        ("合成案例：长条件清单延续引导语",
         "# 申请要求\n申请人须同时满足以下条件：\n" + "\n".join(f"- 条件{i:02}：" + "保留完整的申请材料和审批记录。" * 3 for i in range(8)), 240, None),
        ("合成案例：完整步骤",
         "# 申请办理流程\n" + "\n".join(f"步骤{i:02}：核对本环节的材料，" + "保留书面凭证并完成签字确认。" * 3 for i in range(8)), 240, None),
        ("合成案例：表格按行分组、重复表头与注释（金额为测试数据）",
         "# 测试住宿标准\n| 职级 | 地区 | 测试金额 |\n| --- | --- | --- |\n" + "\n".join(f"| 职级{i:02} | 地区{i:02} | {300 + i} |" for i in range(16)) + "\n\n注：金额仅为合成测试数据，不代表任何公司的制度。", 240, None),
        ("合成案例：制表符文本表格",
         "# 测试授权表\n部门\t审批角色\t测试金额\n" + "\n".join(f"部门{i:02}\t角色{i:02}\t{1000+i}" for i in range(18)), 240, None),
        ("合成案例：普通叙述兜底",
         "这是没有编号的普通说明。" * 12 + "\n\n" + "第二段保留完整句子并记录操作情况。" * 12, 240, None),
    ]
    source_map = {s["id"]: s for s in sources}
    lines = ["# 文档切分预览", "", "真实案例保留来源；合成案例只检查结构，金额和公司名称不代表实际规定。", ""]
    example_reports = []
    for title, text, size, source_id in examples:
        chunks = split_pages([{"text": text, "page": None}], size, min(120, size // 5))
        kept = retained_in_order(text, chunks)
        if not kept:
            raise ValueError(f"Example text retention failed: {title}")
        lines += [f"## {title}", ""]
        if source_id:
            source = source_map[source_id]
            lines += [f"[公开原文]({source['page_url']})；完整快照：`{source['path']}`。", ""]
        lines += [f"本例长度上限 {size} 字符，生成 {len(chunks)} 个片段。", "", "原文：", "", "~~~~text", text, "~~~~", ""]
        for i, chunk in enumerate(chunks, 1):
            lines += [f"### 片段 {i} · {len(chunk['content'])} 字符", "", f"章节路径：{chunk['section'] or '未识别，使用通用文本规则'}", "", "~~~~text", chunk["content"], "~~~~", ""]
        example_reports.append({"title": title, "source_id": source_id, "characters": len(text), "size_limit": size,
                                "chunks": len(chunks), "original_nonwhitespace_text_retained_in_order": kept})
    report = {"strategy": "mixed-structure-v2", "status": "passed",
              "recorded_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
              "parser_sha256": hashlib.sha256((PROJECT / "rag_agent/documents.py").read_bytes()).hexdigest(),
              "public_source_count": len(sources), "public_sources": public_reports,
              "preview_examples": example_reports, "live_model_calls": False, "rag_hit_rate": None,
              "limits": ["structure-based heuristics, not model-based semantic segmentation", "no OCR or complex PDF table reconstruction"]}
    (ROOT / "切分预览.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")
    (ROOT / "validation_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"status": report["status"], "public_sources": len(sources), "preview_examples": len(examples),
                      "public_source_chunks": sum(s["chunks"] for s in public_reports)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
