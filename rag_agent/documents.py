from __future__ import annotations

import re
from bisect import bisect_right
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from pypdf import PdfReader


def parse_document(path: Path, filename: str) -> list[dict]:
    if path.suffix.lower() == ".pdf":
        reader = PdfReader(path)
        if reader.is_encrypted:
            raise ValueError("暂不支持加密 PDF，请先解密后上传。")
        if len(reader.pages) > 1000:
            raise ValueError("初版单个 PDF 最多支持 1000 页，请拆分后上传。")
        pages = [{"text": p.extract_text() or "", "page": i + 1} for i, p in enumerate(reader.pages)]
        if not any(p["text"].strip() for p in pages):
            raise ValueError("未提取到文字：扫描版 PDF 需要先经过 OCR。本初版不包含 OCR。")
    else:
        raw = path.read_bytes()
        for encoding in ("utf-8-sig", "gb18030"):
            try:
                text = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise ValueError("无法识别文本编码，请转换为 UTF-8 后上传。")
        if "\x00" in text:
            raise ValueError("文件不是可解析的文本，请上传 PDF、TXT 或 Markdown。")
        pages = [{"text": text, "page": None}]
    total = sum(len(page["text"]) for page in pages)
    if total > 3_000_000:
        raise ValueError("单个文档提取文本超过 300 万字符，请拆分后上传。")
    if total == 0:
        raise ValueError("文档内容为空。")
    return pages


NUMBER = r"[一二三四五六七八九十百千万零〇两\d\s]+"
ARTICLE = re.compile(rf"^第\s*{NUMBER}条(?:之{NUMBER})?")
CHAPTER = re.compile(rf"^第\s*{NUMBER}(编|篇|章|节)")
BOUNDARIES = (r"\n[ \t]*\n", r"[。！？!?；;][”’」』）\"]*|(?<=[.!?;])\s+", r"\n", r"[ \t]+")
OUTLINE = re.compile(r"^(\d{1,3}(?:[.．](?:\d{1,3}|[A-Za-z]))*)([.．、)]?)(?:[ \t]+|(?=[\u3400-\u9fff]))(.+)$")
CN_OUTLINE = re.compile(r"^([一二三四五六七八九十百]+[、．.]|[（(][一二三四五六七八九十百\d]+[）)])\s*(.+)$")
ITEM = re.compile(rf"^\s*(?:[-*+]\s+|\d+[.)、]\s+|[（(][一二三四五六七八九十百\d]+[）)]|第\s*{NUMBER}步|步骤\s*\d+|Step\s*\d+\b)", re.I)
NOTE = re.compile(r"^\s*(?:注\d*|说明|备注|单位|Notes?)\s*[:：]", re.I)
LABEL = re.compile(r"^(?:目的|适用范围|范围|职责|职责分工|管理要求|审批权限|审批流程|操作流程|办理流程|申请材料|报销标准|注意事项|例外情况|附则|常见问题|Purpose|Scope|Responsibilities|Procedure|Procedures|Exceptions|References|FAQ|Frequently Asked Questions)$", re.I)


def _document_title(line):
    title = line.strip()
    return bool(2 <= len(title) <= 80 and not re.search(r"[。；;:：]", title)
                and re.search(r"(?:制度|办法|手册|规程|指引|程序|流程说明|\bPolicy|\bHandbook|\bProcedure)$", title, re.I))


def _outline(title):
    match = OUTLINE.match(title)
    if not match:
        return None
    number, punctuation, body = match.groups()
    parts = number.replace("．", ".").split(".")
    # Amounts, dates, versions and full list sentences are not section titles.
    if len(body) > 90 or re.search(r"[。；;!?！？.]$", body):
        return None
    if re.match(r"^(?:%|％|元|万元|亿元|小时|分钟|天|倍|kg\b|MB\b|GB\b|USD\b|RMB\b|version\b)", body, re.I):
        return None
    if len(parts) == 1 and not punctuation and len(body) > 35:
        return None
    depth = len(parts) - (len(parts) > 1 and parts[-1] == "0")
    key = tuple(parts[:-1]) if depth == len(parts) and len(parts) > 1 else ()
    return match, (key, depth), 40 + depth - 1


def _outline_families(text):
    counts = Counter()
    fence = None
    for line in text.splitlines():
        marker = re.match(r"^\s*(`{3,}|~{3,})", line)
        if marker:
            token = marker.group(1)
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
            continue
        if fence:
            continue
        title = re.sub(r"^\s*#{1,6}\s+", "", line.strip())
        candidate = _outline(title)
        if candidate:
            counts[candidate[1]] += 1
    return {key for key, count in counts.items() if count >= 2}


def _heading(line: str, outline_families=frozenset()):
    """Return hierarchy rank, label, body offset and Markdown depth for real headings."""
    stripped = line.lstrip(" \t")
    indent = len(line) - len(stripped)
    md = re.match(r"(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$", stripped.rstrip("\n"))
    title = md.group(2) if md else stripped.rstrip("\n")
    bold = re.fullmatch(r"(?:\*\*(.+)\*\*|__(.+)__)", title.strip())
    if bold:
        title = next(value for value in bold.groups() if value is not None)
    if not md and re.search(r"\.{3,}|…{2,}|[·•]{3,}|\t\s*\d+\s*$", title):
        return None  # Preserve table-of-contents text without promoting each entry.
    article, chapter = ARTICLE.match(title), CHAPTER.match(title)
    depth = len(md.group(1)) if md else 0
    if article:
        # A plain article may have its body on the same line as its number.
        label = title if md else re.sub(r"\s+", "", article.group())
        return 70, label, len(line) if md else indent + article.end(), depth
    if chapter:
        rank = {"编": 15, "篇": 16, "章": 20, "节": 30}[chapter.group(1)]
        return rank, title, len(line), depth
    if len(title) <= 220 and (re.match(r"^(?:Q|Question|问题|问)\s*\d*\s*[:：]", title, re.I)
                             or title.endswith(("?", "？")) and not re.search(r"[。；;]", title)):
        return 80, title, len(line), depth
    chinese = CN_OUTLINE.match(title)
    if chinese and len(title) <= 100 and not re.search(r"[。；;]$", title):
        return (45 if chinese.group(1)[0] in "（(" else 40), title, len(line), depth
    numeric = _outline(title)
    if numeric and (md or numeric[1] in outline_families):
        return numeric[2], title, len(line), depth
    if not md and LABEL.fullmatch(title.strip()):
        return 35, title.strip(), len(line), depth
    if bold and len(title) <= 80 and not re.search(r"[。；;]$", title):
        return 35, title, len(line), depth
    if md:
        return depth * 10, title, len(line), depth
    return None


def _structural_units(text: str):
    """Keep article/heading bodies together; fold empty parent headings into the next body."""
    units, stack = [], []
    unit_start = body_start = offset = 0
    fence = None
    outline_families = _outline_families(text)
    list_parent = None
    first_text = len(text) - len(text.lstrip())

    def section():
        path = " / ".join(item[1] for item in stack)
        return path if len(path) <= 160 else path[:75] + " … " + path[-82:]

    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        marker = re.match(r"^[ \t]*(`{3,}|~{3,})", line)
        if marker:
            symbol = marker.group(1)
            if fence is None:
                fence = symbol
            elif symbol[0] == fence[0] and len(symbol) >= len(fence):
                fence = None
            offset += len(line)
            continue
        heading = None if fence or line.startswith(("    ", "\t")) else _heading(line, outline_families)
        if heading is None and not fence and offset <= first_text and _document_title(line):
            heading = (10, line.strip(), len(line), 0)
        if heading is None and not fence and len(line.strip()) <= 80 and line.strip() and index + 1 < len(lines):
            underline = re.fullmatch(r"[ \t]*(={3,}|-{3,})[ \t]*\n?", lines[index + 1])
            if underline and not re.search(r"[。；;]$", line.strip()):
                depth = 1 if underline.group(1).startswith("=") else 2
                heading = (depth * 10, line.strip(), len(line) + len(lines[index + 1]), depth)
        if heading:
            rank, label, body_offset, depth = heading
            article_parent = next((h for h in reversed(stack) if h[0] == 70), None)
            # Subheadings inside an article belong to the article body, rather than
            # fragmenting an otherwise short, complete rule into separate chunks.
            if article_parent and ((rank != 70 and depth and depth > (article_parent[2] or 2) and not CHAPTER.match(label))
                                   or 35 <= rank < 70 and not depth or rank == 80 and not depth):
                offset += len(line)
                continue
            if list_parent is not None and rank <= list_parent:
                list_parent = None
            if 40 <= rank < 70 and not depth:
                prior = text[body_start:offset].rstrip()
                if list_parent is not None and rank > list_parent:
                    offset += len(line)
                    continue
                if prior.endswith((":", "：")):
                    list_parent = stack[-1][0] if stack else rank - 1
                    if rank > list_parent:
                        offset += len(line)
                        continue
            if text[body_start:offset].strip():
                units.append((unit_start, offset, section()))
                unit_start = offset
            while stack and (stack[-1][0] >= rank or depth and stack[-1][2] >= depth):
                stack.pop()
            stack.append((rank, label, depth))
            body_start = offset + body_offset
        offset += len(line)
    if text[unit_start:].strip():
        units.append((unit_start, len(text), section()))
    return units


def _split_long_unit(text: str, start: int, stop: int, size: int, overlap: int):
    """Only subdivide oversized units; overlap stays inside the same unit."""
    while start < stop:
        end = min(start + size, stop)
        forced = False
        if end < stop:
            minimum = start + max(size // 3, overlap + 1)
            for pattern in BOUNDARIES:
                boundaries = [start + m.end() for m in re.finditer(pattern, text[start:end])
                              if start + m.end() >= minimum]
                if boundaries:
                    end = boundaries[-1]
                    break
            else:
                forced = True
        yield start, end
        if end == stop:
            break
        next_start = end
        if overlap:
            lower = max(start + 1, end - overlap)
            boundaries = [lower + m.end() for m in re.finditer("|".join(BOUNDARIES[:3]), text[lower:end])
                          if lower + m.end() < end and text[lower + m.end():end].strip()]
            if boundaries:
                next_start = boundaries[0]
            elif forced:
                next_start = lower
        start = next_start


@dataclass
class _Block:
    start: int
    stop: int
    kind: str = "paragraph"
    header: str = ""
    rows: list[tuple[int, str]] = field(default_factory=list)
    suffix: str = ""
    delimiter: str = "|"


def _cells(line, delimiter="|"):
    if delimiter == "\t":
        return [cell.strip() for cell in line.rstrip("\r\n").split("\t")]
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|") and not line.endswith("\\|"):
        line = line[:-1]
    return [c.strip() for c in re.split(r"(?<!\\)\|", line)]


def _blocks(text, start, stop):
    lines, offset = [], start
    for line in text[start:stop].splitlines(keepends=True):
        lines.append((offset, offset + len(line), line))
        offset += len(line)
    i = 0
    while i < len(lines):
        begin, end, line = lines[i]
        if not line.strip():
            i += 1
            continue
        fence = re.match(r"^\s*(`{3,}|~{3,})", line)
        if fence:
            token = fence.group(1)
            j = i + 1
            while j < len(lines):
                closing = re.match(r"^\s*(" + re.escape(token[0]) + r"{" + str(len(token)) + r",})\s*$", lines[j][2])
                j += 1
                if closing:
                    break
            yield _Block(begin, lines[j - 1][1], "code")
            i = j
            continue
        delimiter, header_lines = "|", 0
        if i + 1 < len(lines) and "|" in line:
            separator = _cells(lines[i + 1][2])
            if len(separator) >= 2 and len(_cells(line)) == len(separator) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in separator):
                header_lines = 2
        if not header_lines and "\t" in line and i + 2 < len(lines):
            columns = len(_cells(line, "\t"))
            if columns >= 2 and all("\t" in lines[k][2] and len(_cells(lines[k][2], "\t")) == columns for k in (i + 1, i + 2)):
                delimiter, header_lines = "\t", 1
        if header_lines:
            columns = len(_cells(line, delimiter))
            j = i + header_lines
            rows = []
            while j < len(lines) and delimiter in lines[j][2] and len(_cells(lines[j][2], delimiter)) == columns:
                rows.append((lines[j][0], lines[j][2]))
                j += 1
            if rows:
                row_end = j
                notes = []
                while j < len(lines) and (not lines[j][2].strip() or NOTE.match(lines[j][2])):
                    if NOTE.match(lines[j][2]):
                        notes.append(lines[j][2].strip())
                    j += 1
                # A blank line belongs to a table only when followed by its note.
                if not notes:
                    j = row_end
                header = "".join(lines[k][2] for k in range(i, i + header_lines)).strip()
                yield _Block(begin, lines[j - 1][1], "table", header, rows, "\n".join(notes), delimiter)
                i = j
                continue
        is_item = bool(ITEM.match(line))
        j = i + 1
        while j < len(lines) and lines[j][2].strip():
            candidate = lines[j][2]
            if ITEM.match(candidate) or re.match(r"^\s*(`{3,}|~{3,})", candidate):
                break
            if "\t" in candidate or "|" in candidate and j + 1 < len(lines) and re.search(r"\|\s*:?-{3,}", lines[j + 1][2]):
                break
            j += 1
        yield _Block(begin, lines[j - 1][1], "item" if is_item else "paragraph")
        i = j


def _unit_prefix(text, start, stop, size):
    """Repeat real source context for long Q&A/list/section continuations."""
    source = text[start:stop].strip()
    prefix = ""
    for line in source.splitlines():
        if not line.strip():
            continue
        heading = _heading(line)
        if heading is None and _document_title(line) and not prefix:
            heading = (10, line.strip(), len(line), 0)
        if not heading:
            break
        label = line[:heading[2]].strip()
        combined = "\n".join(filter(None, (prefix, label)))
        prefix = combined if len(combined) <= size // 3 else label
        if heading[2] < len(line):
            break
    # Retain the lead-in of a condition list, e.g. 'Applicants must meet all of:'.
    for match in re.finditer(r"(?m)^.*$", source[:size]):
        line = match.group().strip()
        if ITEM.match(line) or "|" in line:
            break
        if line.endswith((":", "：")):
            candidate = "\n".join(dict.fromkeys(filter(None, (prefix, line))))
            if len(candidate) <= size // 3:
                prefix = candidate
    return prefix if len(prefix) <= size // 3 else ""


def _table_parts(block, prefix, size, overlap):
    notes = ("\n\n" + block.suffix) if block.suffix else ""
    header = "\n\n".join(filter(None, (prefix, block.header))) + "\n"
    budget = size - len(header) - len(notes)
    if budget < 32:
        # Unusually large headers/notes are retained as ordinary text, rather than
        # silently dropping cells or overflowing the model's input indefinitely.
        return
    group, first = [], block.start
    columns = _cells(block.header.splitlines()[0], block.delimiter)
    for number, (row_start, row) in enumerate(block.rows, 1):
        row = row.strip() if block.delimiter == "|" else row.rstrip("\r\n")
        if len(row) + 1 > budget:
            if group:
                yield first, header + "\n".join(group) + notes
                group = []
            # A single oversized row becomes labelled cells; every continuation
            # carries the row identity and column name instead of a broken row.
            values = _cells(row, block.delimiter)
            identity = f"表格第 {number} 行"
            if values and len(values[0]) <= size // 6:
                identity += " · " + values[0]
            for column, value in zip(columns, values):
                context = "\n".join(filter(None, (prefix, identity, column + "："))) + "\n"
                if len(context) >= size // 2:
                    context = identity + "\n"
                    value = column + "：" + value
                capacity = size - len(context)
                for a, b in _split_long_unit(value, 0, len(value), capacity, min(overlap, capacity // 4)):
                    yield row_start, context + value[a:b].strip()
            continue
        if group and sum(len(x) + 1 for x in group) + len(row) + 1 > budget:
            yield first, header + "\n".join(group) + notes
            group = []
        if not group:
            first = row_start
        group.append(row)
    if group:
        yield first, header + "\n".join(group) + notes
    if any(len(row.strip()) + 1 > budget for _, row in block.rows) and block.suffix:
        for a, b in _split_long_unit(block.suffix, 0, len(block.suffix), size, min(overlap, size // 4)):
            yield block.stop - len(block.suffix), block.suffix[a:b].strip()


def _code_parts(text, block, prefix, size):
    lines = text[block.start:block.stop].strip().splitlines()
    opening = lines[0].strip()
    marker = re.match(r"(`{3,}|~{3,})", opening).group(1)
    closing = lines[-1].strip()
    closed = bool(re.fullmatch(re.escape(marker[0]) + "{" + str(len(marker)) + ",}", closing))
    body = lines[1:-1] if closed else lines[1:]
    head = ((prefix + "\n\n") if prefix else "") + opening + "\n"
    tail = "\n" + (closing if closed else marker)
    capacity = size - len(head) - len(tail)
    if capacity < 32:
        return
    group = []
    for line in body:
        if group and len("\n".join(group + [line])) > capacity:
            yield block.start, head + "\n".join(group) + tail
            group = []
        if len(line) > capacity:
            for start in range(0, len(line), capacity):
                yield block.start, head + line[start:start + capacity] + tail
        else:
            group.append(line)
    if group:
        yield block.start, head + "\n".join(group) + tail


def _split_unit(text, start, stop, size, overlap):
    if len(text[start:stop].strip()) <= size:
        yield start, text[start:stop].strip()
        return
    prefix = _unit_prefix(text, start, stop, size)
    capacity = size - len(prefix) - (2 if prefix else 0)
    overlap = min(overlap, capacity // 3)
    pending_start = pending_stop = None

    def normal(a, b):
        for left, right in _split_long_unit(text, a, b, capacity, overlap):
            value = text[left:right].strip()
            if prefix and not value.startswith(prefix):
                value = prefix + "\n\n" + value
            if value:
                yield left, value

    def only_context(a, b):
        return "".join(text[a:b].split()) == "".join(prefix.split())

    for block in _blocks(text, start, stop):
        if block.kind in {"table", "code"}:
            pieces = list(_table_parts(block, prefix, size, overlap)) if block.kind == "table" else list(_code_parts(text, block, prefix, size))
            if pieces:
                if pending_start is not None:
                    if not only_context(pending_start, pending_stop):
                        yield from normal(pending_start, pending_stop)
                    pending_start = pending_stop = None
                yield from pieces
                continue
        if pending_start is not None and block.stop - pending_start > capacity:
            if not only_context(pending_start, pending_stop):
                yield from normal(pending_start, pending_stop)
            pending_start = pending_stop = None
        if block.stop - block.start > capacity:
            yield from normal(block.start, block.stop)
        elif pending_start is None:
            pending_start, pending_stop = block.start, block.stop
        else:
            pending_stop = block.stop
    if pending_start is not None:
        yield from normal(pending_start, pending_stop)


def split_pages(pages: list[dict], size: int, overlap: int) -> list[dict]:
    """Structure first: clauses, outlines, Q&A, lists and tables, then a size limit.

    PDF page breaks do not split a continuous article. `page` is its chunk's start page.
    Short articles stay separate, including their subheadings, with no overlap across articles.
    """
    if size <= 0 or not 0 <= overlap < size:
        raise ValueError("片段大小和重叠范围无效。")
    texts, page_starts, page_numbers = [], [], []
    offset = 0
    for page in pages:
        text = page["text"].replace("\r\n", "\n").replace("\r", "\n")
        if not text.strip():
            continue
        page_starts.append(offset)
        page_numbers.append(page["page"])
        texts.append(text + "\n")
        offset += len(text) + 1
    text = "".join(texts)
    result = []
    for unit_start, unit_stop, section in _structural_units(text):
        for start, content in _split_unit(text, unit_start, unit_stop, size, overlap):
            if content:
                nonspace = re.compile(r"\S").search(text, start, unit_stop)
                first = nonspace.start() if nonspace else start
                page = page_numbers[bisect_right(page_starts, first) - 1]
                result.append({"content": content, "page": page, "section": section})
    if not result:
        raise ValueError("文档中没有可用的文字片段。")
    return result


def document_topic(pages: list[dict], filename: str) -> str:
    for page in pages[:2]:
        heading = re.search(r"^#\s+(.+)$", page["text"], re.M)
        if heading:
            return heading.group(1).strip()[:160]
        for line in page["text"].splitlines()[:5]:
            if _document_title(line):
                return line.strip()[:160]
    return Path(filename).stem[:160]
