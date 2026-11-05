from __future__ import annotations

import logging
import math
import re
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from .documents import document_topic, parse_document, split_pages
from .providers import ProviderError
from .security import now, uid

log = logging.getLogger(__name__)


def tokens(text: str) -> list[str]:
    result = re.findall(r"[a-z0-9_]+", text.lower())
    for part in re.findall(r"[\u3400-\u9fff]+", text):
        result.extend(part[i:i + 2] for i in range(max(1, len(part) - 1)))
    return result


class Knowledge:
    def __init__(self, db, settings, embeddings):
        self.db, self.settings, self.embeddings = db, settings, embeddings
        self.upload_dir = settings.data_dir / "uploads"
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="rag-ingest")
        self.jobs = {}
        self.lock = threading.Lock()
        # Interrupted work is explicit and can be retried; never mark it successful.
        with db.connect() as conn:
            conn.execute("""UPDATE documents SET status=CASE WHEN EXISTS
                (SELECT 1 FROM chunks WHERE document_id=documents.id) THEN 'parsed' ELSE 'error' END,
                error='上次任务因服务退出中断，请重试解析或建立向量。'
                WHERE status IN ('queued','parsing','indexing')""")

    def list_documents(self):
        return self.db.rows("""SELECT d.*,
            (SELECT COUNT(*) FROM chunks c WHERE c.document_id=d.id) AS chunk_count,
            (SELECT COUNT(*) FROM chunks c JOIN vectors v ON v.chunk_id=c.id
                WHERE c.document_id=d.id AND v.embedding_key=?) AS vector_count
            FROM documents d ORDER BY d.created_at DESC""", (self.embeddings.key,))

    def chunks(self, document_id):
        return self.db.rows("""SELECT c.*, EXISTS(SELECT 1 FROM vectors v WHERE v.chunk_id=c.id
            AND v.embedding_key=?) AS has_vector FROM chunks c WHERE c.document_id=? ORDER BY ordinal""",
                            (self.embeddings.key, document_id))

    def schedule(self, document_id, kind):
        with self.lock:
            existing = self.jobs.get(document_id)
            if existing is not None and not existing.done():
                raise ValueError("该文档正在处理中，请等待完成后再操作。")
            with self.db.connect() as conn:
                row = conn.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
                if row is None:
                    raise ValueError("文档不存在。")
                if kind == "index" and not conn.execute("SELECT 1 FROM chunks WHERE document_id=?", (document_id,)).fetchone():
                    raise ValueError("请先成功解析文档，再建立向量。")
                conn.execute("UPDATE documents SET status=?, error='',updated_at=? WHERE id=?",
                             ("queued" if kind == "parse" else "indexing", now(), document_id))
            self.jobs[document_id] = self.executor.submit(self._run, document_id, kind)

    def wait(self, document_id, timeout=10):
        future = self.jobs.get(document_id)
        if future:
            future.result(timeout=timeout)

    def busy(self, document_id):
        future = self.jobs.get(document_id)
        return bool(future and not future.done())

    def _run(self, document_id, kind):
        try:
            doc = self.db.one("SELECT * FROM documents WHERE id=?", (document_id,))
            if not doc:
                return
            revision = doc["revision"]
            if kind == "parse":
                with self.db.connect() as conn:
                    conn.execute("UPDATE documents SET status='parsing' WHERE id=?", (document_id,))
                pages = parse_document(self.upload_dir / doc["stored_name"], doc["filename"])
                chunks = split_pages(pages, self.settings.chunk_size, self.settings.chunk_overlap)
                topic = document_topic(pages, doc["filename"])
                with self.db.connect() as conn:
                    current = conn.execute("SELECT revision FROM documents WHERE id=?", (document_id,)).fetchone()
                    if not current:
                        return
                    if current["revision"] != revision:
                        raise ProviderError("解析期间文档发生变化，请重新解析。")
                    conn.execute("DELETE FROM chunks WHERE document_id=?", (document_id,))
                    conn.executemany("INSERT INTO chunks(id,document_id,ordinal,content,page,section) VALUES(?,?,?,?,?,?)",
                                     [(uid(), document_id, i + 1, c["content"], c["page"], c["section"]) for i, c in enumerate(chunks)])
                    conn.execute("UPDATE documents SET status='parsed',topic=?,error='',revision=revision+1,updated_at=? WHERE id=?",
                                 (topic, now(), document_id))
            else:
                chunks = self.chunks(document_id)
                batches = []
                for start in range(0, len(chunks), 16):
                    # Stop between batches if a user deleted or changed the document.
                    current = self.db.one("SELECT revision FROM documents WHERE id=?", (document_id,))
                    if not current:
                        return
                    if current["revision"] != revision:
                        raise ProviderError("建立向量期间文档发生变化，请重新建立向量。")
                    batches.append(self.embeddings.encode([c["content"] for c in chunks[start:start + 16]]))
                values = np.concatenate(batches, axis=0)
                with self.db.connect() as conn:
                    conn.execute("BEGIN IMMEDIATE")
                    current = conn.execute("SELECT revision FROM documents WHERE id=?", (document_id,)).fetchone()
                    if not current:
                        return
                    if current["revision"] != revision:
                        raise ProviderError("建立向量期间文档发生变化，请重新建立向量。")
                    conn.execute("DELETE FROM vectors WHERE chunk_id IN (SELECT id FROM chunks WHERE document_id=?)", (document_id,))
                    conn.executemany("INSERT INTO vectors(chunk_id,embedding_key,dimension,value) VALUES(?,?,?,?)",
                                     [(c["id"], self.embeddings.key, 1024, np.asarray(v, dtype=np.float32).tobytes())
                                      for c, v in zip(chunks, values, strict=True)])
                    conn.execute("UPDATE documents SET status='ready',error='',updated_at=? WHERE id=?", (now(), document_id))
        except Exception as exc:
            log.exception("Document %s %s failed", document_id, kind)
            message = str(exc) if isinstance(exc, (ValueError, ProviderError)) else "处理失败，请检查文件内容与服务日志。"
            with self.db.connect() as conn:
                conn.execute("""UPDATE documents SET status=CASE WHEN EXISTS
                    (SELECT 1 FROM chunks WHERE document_id=documents.id) THEN 'parsed' ELSE 'error' END,
                    error=?,updated_at=? WHERE id=?""", (message[:1000], now(), document_id))

    def search(self, query, document_ids=None, limit=5):
        if not query.strip():
            return []
        where, args = "", [self.embeddings.key]
        if document_ids:
            where = " AND d.id IN (" + ",".join("?" for _ in document_ids) + ")"
            args.extend(document_ids)
        rows = self.db.rows("""SELECT c.*,d.filename,d.topic,v.value FROM chunks c
            JOIN documents d ON d.id=c.document_id JOIN vectors v ON v.chunk_id=c.id
            WHERE v.embedding_key=?""" + where, args)
        if not rows:
            raise ProviderError("当前查询范围内还没有可用向量。请让管理员上传文档、检查解析结果并点击「建立向量」。")
        query_vector = self.embeddings.encode([query])[0]
        vectors = np.stack([np.frombuffer(row.pop("value"), dtype=np.float32) for row in rows])
        cosine = vectors @ query_vector
        query_tokens = set(tokens(query))
        bags = [Counter(tokens(row["content"])) for row in rows]
        lengths = [sum(bag.values()) for bag in bags]
        avg = sum(lengths) / max(1, len(rows)) or 1
        dfs = {term: sum(term in bag for bag in bags) for term in query_tokens}
        lexical = []
        for bag, length in zip(bags, lengths):
            score = 0.0
            for term in query_tokens:
                frequency = bag.get(term, 0)
                if frequency:
                    idf = math.log(1 + (len(rows) - dfs[term] + 0.5) / (dfs[term] + 0.5))
                    score += idf * frequency * 2.2 / (frequency + 1.2 * (0.25 + 0.75 * length / avg))
            lexical.append(score)
        # RRF combines ranks rather than treating incompatible scores as confidence.
        fused = Counter()
        for scores in (cosine, lexical):
            for rank, index in enumerate(sorted(range(len(rows)), key=lambda i: scores[i], reverse=True)[:30]):
                if scores[index] > 0:
                    fused[index] += 1 / (60 + rank + 1)
        indices = sorted(fused, key=lambda i: fused[i], reverse=True)
        results, seen = [], set()
        for index in indices:
            if cosine[index] < 0.25 and lexical[index] <= 0:
                continue
            signature = rows[index]["content"].strip()
            if signature in seen:
                continue
            seen.add(signature)
            results.append({**rows[index], "cosine": round(float(cosine[index]), 4), "rank_score": round(fused[index], 6)})
            if len(results) >= limit:
                break
        return results

    def read_neighbors(self, chunk_id, document_ids=None):
        chunk = self.db.one("SELECT * FROM chunks WHERE id=?", (chunk_id,))
        if not chunk or (document_ids and chunk["document_id"] not in document_ids):
            return []
        return self.db.rows("""SELECT c.*,d.filename,d.topic FROM chunks c JOIN documents d ON d.id=c.document_id
            WHERE c.document_id=? AND c.ordinal BETWEEN ? AND ? ORDER BY c.ordinal""",
                            (chunk["document_id"], chunk["ordinal"] - 1, chunk["ordinal"] + 1))
