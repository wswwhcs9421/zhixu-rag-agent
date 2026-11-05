"""Business-document layout regressions; synthetic cases are not company policy claims."""
import hashlib
import json
from pathlib import Path

import pytest

from rag_agent.documents import document_topic, split_pages

ROOT = Path(__file__).resolve().parents[1] / "evaluation/chunking_examples"


def split(text, size=1000, overlap=120):
    return split_pages([{"text": text, "page": None}], size, overlap)


def test_chinese_outline_without_articles():
    text = "# 费用管理办法\n一、适用范围\n本办法适用于全体员工。\n二、审批要求\n预算外支出需要特别审批。\n（一）普通费用\n由部门负责人审批。\n（二）特殊费用\n依授权表审批。"
    chunks = split(text)
    assert len(chunks) == 4
    assert chunks[2]["section"] == "费用管理办法 / 二、审批要求 / （一）普通费用"
    assert "预算外支出" in chunks[1]["content"]
    assert "特殊费用" not in chunks[2]["content"]


def test_plain_document_title_is_retained_in_section_path_and_topic():
    text = "星海公司费用报销管理办法\n适用范围\n全体员工。\n审批流程\n按权限办理。"
    chunks = split(text)
    assert chunks[0]["section"] == "星海公司费用报销管理办法 / 适用范围"
    assert chunks[1]["section"] == "星海公司费用报销管理办法 / 审批流程"
    assert document_topic([{"text": text, "page": None}], "upload.txt") == "星海公司费用报销管理办法"


def test_sop_decimal_outline_and_alphanumeric_siblings():
    text = "# 采购程序\n1.0 目的\n规范采购。\n2.0 范围\n适用于采购业务。\n2.1 国内采购\n国内规则。\n2.2 境外采购\n境外规则。\n3.0 审查\n3.A 采购审查\n审查合同。\n3.B 法律审查\n审查条款。"
    chunks = split(text)
    assert any(c["section"].endswith("2.0 范围 / 2.1 国内采购") for c in chunks)
    assert any(c["section"].endswith("3.0 审查 / 3.A 采购审查") for c in chunks)
    assert any("3.B 法律审查" in c["section"] for c in chunks)


def test_simple_numeric_heading_needs_a_family():
    chunks = split("1. 申请\n填写申请单。\n2. 审核\n核对预算。")
    assert len(chunks) == 2
    assert chunks[1]["section"] == "2. 审核"
    isolated = split("3.14 内部记录\n这个孤立数字缺少编号层级证据。")
    assert isolated[0]["section"] == ""


@pytest.mark.parametrize("line", ["2026.11.02 更新记录", "3.14 元/天", "1.5 倍工资", "500 元限额", "1.2.3", "https://example.com/policy/1.2"])
def test_dates_amounts_versions_and_urls_are_not_headings(line):
    chunks = split("# 管理说明\n正文起始。\n" + line + "\n正文结束。")
    assert len(chunks) == 1
    assert chunks[0]["section"] == "管理说明"
    assert line in chunks[0]["content"]


def test_directory_entries_do_not_become_real_sections():
    text = "# 员工手册\n目录\n一、考勤…………3\n二、报销......8\n说明\n这是正文说明。"
    chunks = split(text)
    assert not any("考勤" in c["section"] or "报销" in c["section"] for c in chunks)
    assert any("一、考勤…………3" in c["content"] for c in chunks)


def test_labelled_faq_keeps_question_and_answer_together():
    text = "# 报销问答\nQ1：没有发票能否报销？\nA1：应按有效制度补齐合规凭证，不能自行绕过审核。\nQ2：谁负责审批？\nA2：以公司授权表为准。"
    chunks = split(text)
    assert len(chunks) == 2
    assert "Q1：" in chunks[0]["content"] and "A1：" in chunks[0]["content"]
    assert "Q2：" not in chunks[0]["content"]


def test_numbered_and_bold_questions_keep_their_answers():
    text = "# 常见问题\n1. 发票丢失怎么办？\n答：依有效制度处理，补充证明材料。\n**2. 审批需要多久？**\n答：资料未规定统一时间。"
    chunks = split(text)
    assert len(chunks) == 2
    assert "补充证明材料" in chunks[0]["content"]
    assert "资料未规定统一时间" in chunks[1]["content"]
    assert "审批需要多久" not in chunks[0]["content"]


def test_setext_and_bold_section_titles():
    text = "员工手册\n========\n审批要求\n--------\n审批正文。\n**例外规定**\n例外正文。"
    chunks = split(text)
    assert any(c["section"] == "员工手册 / 审批要求" and "审批正文" in c["content"] for c in chunks)
    assert any(c["section"] == "员工手册 / 审批要求 / 例外规定" for c in chunks)


def test_unmarked_questions_and_long_answer_repeat_the_question():
    question = "How do suppliers register for the portal?"
    answer = " ".join(f"Step {i} retains request identifier {i:03}." for i in range(30))
    chunks = split("# Supplier FAQ\n" + question + "\n" + answer + "\nCan suppliers use email?\nYes, follow the approved process.", 250, 40)
    first = [c for c in chunks if question in c["section"]]
    assert len(first) > 1
    assert all(question in c["content"] for c in first)
    assert all(len(c["content"]) <= 250 for c in chunks)
    assert "Can suppliers use email?" in chunks[-1]["content"]


def test_long_faq_with_blank_lines_has_no_question_only_fragment():
    question = "Q1：费用凭证由谁审核？"
    answer = "".join(f"财务审核凭证{i:02}并确认其符合要求。" for i in range(25))
    chunks = split("# 费用问答\n\n" + question + "\n\n" + answer, 230, 40)
    assert len(chunks) > 1
    assert all(question in c["content"] and "财务审核凭证" in c["content"] for c in chunks)


def test_short_workflow_retains_all_steps_and_order():
    text = "# 付款流程\n第一步：申请人提交单据。\n第二步：部门负责人核实业务。\n第三步：财务审核后办理付款。"
    chunks = split(text)
    assert len(chunks) == 1
    assert chunks[0]["content"].index("第一步") < chunks[0]["content"].index("第二步") < chunks[0]["content"].index("第三步")


def test_long_workflow_splits_between_complete_steps():
    steps = [f"步骤{i:02}：核对申请编号{i:02}，" + "保留单据并完成该环节的签字确认" * 2 + "。" for i in range(10)]
    chunks = split("# 采购办理流程\n" + "\n".join(steps), 230, 40)
    assert len(chunks) > 1
    assert all(any(step in c["content"] for c in chunks) for step in steps)
    assert all("采购办理流程" in c["section"] for c in chunks)


def test_long_condition_list_repeats_its_lead_in_without_cutting_items():
    lead = "申请人须同时满足以下条件："
    items = [f"- 条件{i:02}：" + "必须保留完整的审批记录和相关凭证" * 2 + "。" for i in range(12)]
    chunks = split("# 申请要求\n" + lead + "\n" + "\n".join(items), 220, 40)
    assert len(chunks) > 1
    assert all(lead in c["content"] for c in chunks)
    assert all(any(item in c["content"] for c in chunks) for item in items)


def test_numbered_conditions_after_colon_stay_with_the_parent_rule():
    text = "# 申请制度\n一、申请条件\n必须满足以下要求：\n（一）提交申请单\n（二）保留审批记录\n二、违规处理\n按有效制度执行。"
    chunks = split(text)
    assert len(chunks) == 2
    assert all(x in chunks[0]["content"] for x in ["必须满足以下要求", "（一）", "（二）"])
    assert "二、违规处理" not in chunks[0]["content"]


def test_markdown_table_groups_repeat_header_and_notes_keep_rows_whole():
    header = "| 职级 | 城市 | 住宿上限（元/晚） |\n| --- | --- | --- |"
    rows = [f"| 职级{i:02} | 城市{i:02} | {300 + i} |" for i in range(20)]
    note = "注：以上金额仅为合成测试数据，不代表实际报销制度。"
    chunks = split("# 住宿标准\n" + header + "\n" + "\n".join(rows) + "\n\n" + note, 240, 40)
    tables = [c for c in chunks if "| 职级 |" in c["content"]]
    assert len(tables) > 1
    assert all(header in c["content"] and note in c["content"] for c in tables)
    assert all(any(row in c["content"] for c in tables) for row in rows)
    assert all(len(c["content"]) <= 240 for c in chunks)


def test_tab_separated_text_table_preserves_labels():
    header = "部门\t审批角色\t测试金额"
    rows = [f"部门{i:02}\t角色{i:02}\t{1000 + i}" for i in range(20)]
    chunks = split("# 授权表\n" + header + "\n" + "\n".join(rows), 220, 40)
    assert all(any(row in c["content"] for c in chunks) for row in rows)
    table_chunks = [c for c in chunks if "部门00" in c["content"] or "部门10" in c["content"]]
    assert all(header in c["content"] for c in table_chunks)


def test_tables_keep_empty_and_escaped_cells():
    rows = [f"| 部门{i:02} | 甲\\|乙 | |" for i in range(20)]
    header = "| 部门 | 备注 | 金额 |\n| --- | --- | --- |"
    chunks = split("# 说明表\n" + header + "\n" + "\n".join(rows), 220, 40)
    assert all(any(row in c["content"] for c in chunks) for row in rows)
    assert sum(header in c["content"] for c in chunks) > 1


def test_single_oversized_table_cell_keeps_row_and_column_identity():
    value = "甲乙丙丁审批材料必须完整保留。" * 70
    text = "# 材料要求\n| 编号 | 说明 |\n| --- | --- |\n| R001 | " + value + " |"
    chunks = split(text, 230, 40)
    cells = [c for c in chunks if "说明：" in c["content"]]
    assert len(cells) > 1
    assert all("R001" in c["content"] and len(c["content"]) <= 230 for c in cells)
    assert any("编号：" in c["content"] for c in chunks)


def test_long_code_block_remains_fenced_and_does_not_create_fake_headings():
    lines = [f"# example-{i:02}: this is a comment, not a policy heading" for i in range(20)]
    chunks = split("# 操作示例\n```text\n" + "\n".join(lines) + "\n```", 240, 40)
    assert len(chunks) > 1
    assert all(c["section"] == "操作示例" for c in chunks)
    assert all("```text\n" in c["content"] and c["content"].endswith("```") for c in chunks)
    assert all(any(line in c["content"] for c in chunks) for line in lines)


def test_public_enterprise_policy_snapshots_retain_text():
    manifest = json.loads((ROOT / "sources.json").read_text(encoding="utf-8"))
    assert len(manifest) == 8
    for source in manifest:
        path = ROOT / source["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == source["sha256"]
        text = path.read_text(encoding="utf-8")
        chunks = split(text)
        assert chunks and all(0 < len(c["content"]) <= 1000 for c in chunks), source["id"]
        # Original non-whitespace text must survive in order. Extra repeated
        # headings/lead-ins may be present in continuation fragments.
        original = "".join(text.split())
        index = 0
        for character in "".join("".join(c["content"].split()) for c in chunks):
            if index < len(original) and character == original[index]:
                index += 1
        assert index == len(original), (source["id"], index, len(original))


def test_real_numeric_policy_and_faq_work_after_markdown_heading_marks_are_removed():
    import re

    numeric = (ROOT / "public_sources/gitlab_expenses.md").read_text(encoding="utf-8")
    faq = (ROOT / "public_sources/gitlab_faq.md").read_text(encoding="utf-8")
    numeric_chunks = split(re.sub(r"(?m)^#{1,6}\s+", "", numeric))
    assert any("4.3 Missing Receipt Affidavit" in c["section"] for c in numeric_chunks)
    faq_chunks = split(re.sub(r"(?m)^#{1,6}\s+", "", faq))
    assert any("How do suppliers register for the CSP?" in c["section"] for c in faq_chunks)
    matching = [c for c in faq_chunks if "How do suppliers register for the CSP?" in c["section"]]
    assert matching and any("supplier" in c["content"].lower() for c in matching)
