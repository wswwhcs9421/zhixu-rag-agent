import asyncio
import hashlib
import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

from rag_agent.app import create_app
from rag_agent.config import Settings
from rag_agent.knowledge import tokens
from rag_agent.providers import ProviderError


class TestEmbeddings:
    """Explicit test double, never used by the application or real documents."""
    __test__ = False
    key = "test-embedding-v1"

    def status(self):
        return {"mode": "api", "model": "test-double", "dimension": 1024, "loaded": True, "runtime_installed": True}

    def encode(self, texts):
        vectors = np.zeros((len(texts), 1024), dtype=np.float32)
        for i, text in enumerate(texts):
            for term in tokens(text) or ["empty"]:
                index = int(hashlib.sha256(term.encode()).hexdigest()[:8], 16) % 1024
                vectors[i, index] += 1
        return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)


class TestLLM:
    __test__ = False
    configured = True

    async def complete(self, messages, tools=None, required=False):
        last_user = next(m["content"] for m in reversed(messages) if m["role"] == "user")
        if messages[-1]["role"] == "user":
            return {"role": "assistant", "content": None, "tool_calls": [{"id": "test-call", "type": "function", "function": {"name": "search_knowledge", "arguments": json.dumps({"query": last_user}, ensure_ascii=False)}}]}
        return {"role": "assistant", "content": "根据当前资料，住宿上限为 500 元。[S1]"}


@pytest.fixture
def env(tmp_path):
    settings = Settings(data_dir=tmp_path, admin_password="Admin-test-123456", bge_mode="api", deepseek_model="test-double")
    app = create_app(settings, TestEmbeddings(), TestLLM())
    with TestClient(app) as client:
        response = client.post("/api/auth/login", json={"username": "admin", "password": "Admin-test-123456"})
        assert response.status_code == 200
        yield app, client


def upload(app, client, name="policy.md", content="# 差旅制度\n\n上海出差的住宿上限为每天 500 元。报销需要发票与审批单。"):
    response = client.post("/api/documents", files={"file": (name, content.encode(), "text/plain")})
    assert response.status_code == 201, response.text
    doc_id = response.json()["id"]
    app.state.knowledge.wait(doc_id)
    return doc_id


def index(app, client, doc_id):
    response = client.post(f"/api/documents/{doc_id}/index")
    assert response.status_code == 200, response.text
    app.state.knowledge.wait(doc_id)


def reader(app, client, name="reader"):
    response = client.post("/api/users", json={"username": name, "password": "Reader-test-12345", "role": "reader"})
    assert response.status_code == 201
    result = TestClient(app)
    assert result.post("/api/auth/login", json={"username": name, "password": "Reader-test-12345"}).status_code == 200
    return result, response.json()["id"]


def test_document_lifecycle_and_vector_invalidation(env):
    app, client = env
    doc_id = upload(app, client)
    overview = client.get("/api/overview").json()
    assert overview["counts"] == {"documents": 1, "parsed": 1, "chunks": 1, "vectors": 0}
    assert overview["documents"][0]["topic"] == "差旅制度"
    assert "stored_name" not in overview["documents"][0]
    index(app, client, doc_id)
    assert client.get("/api/overview").json()["counts"]["vectors"] == 1
    chunk = client.get(f"/api/documents/{doc_id}/chunks").json()[0]
    assert client.patch(f"/api/chunks/{chunk['id']}", json={"content": "住宿标准已经变更为 600 元。"}).status_code == 200
    assert client.get("/api/overview").json()["counts"]["vectors"] == 0
    assert client.post("/api/search", json={"query": "住宿标准"}).status_code == 503
    index(app, client, doc_id)
    results = client.post("/api/search", json={"query": "住宿标准"}).json()["results"]
    assert "600" in results[0]["content"]
    assert client.post(f"/api/documents/{doc_id}/chunks", json={"content": "补充条款：保留原始发票。"}).status_code == 201
    assert client.get("/api/overview").json()["counts"]["chunks"] == 2
    assert client.delete(f"/api/documents/{doc_id}").status_code == 200
    assert app.state.db.one("SELECT COUNT(*) AS n FROM vectors")["n"] == 0
    assert not list((app.state.settings.data_dir / "uploads").iterdir())


def test_reparse_replaces_chunks_and_requires_new_vectors(env):
    app, client = env
    text = "# 采购制度\n\n第一条 预算外采购必须先调整预算。\n第二条 发票异常应当拒绝付款。"
    doc_id = upload(app, client, "procurement.md", text)
    index(app, client, doc_id)
    old_ids = {c["id"] for c in client.get(f"/api/documents/{doc_id}/chunks").json()}
    assert len(old_ids) == 2
    assert client.post(f"/api/documents/{doc_id}/parse").status_code == 200
    app.state.knowledge.wait(doc_id)
    chunks = client.get(f"/api/documents/{doc_id}/chunks").json()
    assert len(chunks) == 2 and not old_ids.intersection(c["id"] for c in chunks)
    assert not any(c["has_vector"] for c in chunks)
    assert app.state.db.one("SELECT COUNT(*) AS n FROM vectors")["n"] == 0
    index(app, client, doc_id)
    results = client.post("/api/search", json={"query": "预算外采购", "document_ids": [doc_id]}).json()["results"]
    assert any("先调整预算" in r["content"] for r in results)


def test_reader_cannot_mutate_any_admin_resource(env):
    app, client = env
    doc_id = upload(app, client)
    index(app, client, doc_id)
    chunk_id = client.get(f"/api/documents/{doc_id}/chunks").json()[0]["id"]
    member, member_id = reader(app, client)
    mutations = [
        ("post", "/api/users", {"username": "eviluser", "password": "Password-123456", "role": "admin"}),
        ("patch", f"/api/users/{member_id}", {"role": "admin"}),
        ("delete", f"/api/users/{member_id}", None),
        ("patch", f"/api/documents/{doc_id}", {"topic": "unauthorized"}),
        ("delete", f"/api/documents/{doc_id}", None),
        ("post", f"/api/documents/{doc_id}/index", None),
        ("post", f"/api/documents/{doc_id}/parse", None),
        ("post", f"/api/documents/{doc_id}/chunks", {"content": "unauthorized"}),
        ("patch", f"/api/chunks/{chunk_id}", {"content": "unauthorized"}),
        ("delete", f"/api/chunks/{chunk_id}", None),
    ]
    for method, path, payload in mutations:
        kwargs = {"json": payload} if payload is not None else {}
        assert member.request(method.upper(), path, **kwargs).status_code == 403, path
    assert member.post("/api/documents", files={"file": ("evil.txt", b"content")}).status_code == 403
    assert member.get("/api/users").status_code == 403
    assert member.get("/api/audit").status_code == 403
    assert member.get("/api/overview").status_code == 200
    assert member.get(f"/api/documents/{doc_id}/chunks").status_code == 200
    assert member.post("/api/search", json={"query": "上海住宿"}).status_code == 200
    reply = member.post("/api/chat", json={"question": "上海住宿上限是多少？"})
    assert reply.status_code == 200, reply.text
    assert reply.json()["citations"][0]["document_id"] == doc_id
    member.close()


def test_passwords_sessions_roles_and_cross_site_protection(env):
    app, client = env
    row = app.state.db.one("SELECT * FROM users WHERE username='admin'")
    assert row["password_hash"] != "Admin-test-123456"
    assert client.cookies.get("rag_session") != app.state.db.one("SELECT token_hash FROM sessions")["token_hash"]
    assert client.post("/api/auth/logout", headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/auth/logout", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.get("/").headers["content-security-policy"].startswith("default-src 'self'")
    assert client.patch(f"/api/users/{row['id']}", json={"role": "reader"}).status_code == 400
    assert client.delete(f"/api/users/{row['id']}").status_code == 400
    member, member_id = reader(app, client)
    assert client.patch(f"/api/users/{member_id}", json={"active": False}).status_code == 200
    assert member.get("/api/auth/me").status_code == 401
    member.close()
    assert client.post("/api/auth/password", json={"old_password": "wrong", "new_password": "New-password-12345"}).status_code == 400
    assert client.post("/api/auth/password", json={"old_password": "Admin-test-123456", "new_password": "New-password-12345"}).status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_conversation_ownership_and_citation_snapshot(env):
    app, client = env
    doc_id = upload(app, client)
    index(app, client, doc_id)
    result = client.post("/api/chat", json={"question": "上海住宿上限？"})
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["trace"][0]["tool"] == "search_knowledge"
    assert "[S1]" in body["answer"]
    assert body["citations"][0]["ordinal"] == 1
    member, _ = reader(app, client)
    cid = body["conversation_id"]
    assert member.get(f"/api/conversations/{cid}").status_code == 404
    assert member.post("/api/chat", json={"question": "偷读会话", "conversation_id": cid}).status_code == 404
    assert client.delete(f"/api/documents/{doc_id}").status_code == 200
    history = client.get(f"/api/conversations/{cid}").json()
    assert "500" in history["messages"][-1]["citations"][0]["content"]
    assert history["messages"][-1]["citations"][0]["ordinal"] == 1
    member.close()


def test_unsupported_files_scope_and_missing_models(env):
    app, client = env
    assert client.post("/api/documents", files={"file": ("evil.exe", b"MZ")}).status_code == 400
    assert client.post("/api/documents", files={"file": ("empty.txt", b"")}).status_code == 400
    assert client.post("/api/search", json={"query": "hello"}).status_code == 503
    assert client.post("/api/search", json={"query": "hello", "document_ids": ["nonexistent"]}).status_code == 404
    doc_id = upload(app, client, "../../safe.txt", "内容必须仍保存在上传目录中。")
    row = app.state.db.one("SELECT * FROM documents WHERE id=?", (doc_id,))
    assert row["filename"] == "safe.txt" and "/" not in row["stored_name"]
    assert (app.state.knowledge.upload_dir / row["stored_name"]).is_file()
    # A failed real provider must not fabricate vectors or mark the document ready.
    def fail(texts):
        raise ProviderError("test provider unavailable")
    app.state.knowledge.embeddings.encode = fail
    index(app, client, doc_id)
    overview = client.get("/api/overview").json()
    assert overview["counts"]["vectors"] == 0
    assert overview["documents"][0]["status"] == "parsed"
    assert "unavailable" in overview["documents"][0]["error"]


def test_embedding_config_change_excludes_stale_vectors(env):
    app, client = env
    doc_id = upload(app, client)
    index(app, client, doc_id)
    app.state.knowledge.embeddings.key = "different-model-config"
    overview = client.get("/api/overview").json()
    assert overview["counts"]["vectors"] == 0
    assert overview["documents"][0]["status"] == "parsed"
    assert client.post("/api/search", json={"query": "住宿"}).status_code == 503


def test_invalid_citation_is_not_published(env):
    app, client = env
    doc_id = upload(app, client)
    index(app, client, doc_id)
    original = app.state.agent.llm.complete
    async def invalid(messages, tools=None, required=False):
        if messages[-1]["role"] == "user":
            return await original(messages, tools, required)
        return {"role": "assistant", "content": "伪造的来源 [S999]"}
    app.state.agent.llm.complete = invalid
    response = client.post("/api/chat", json={"question": "上海住宿上限"})
    assert response.status_code == 503
    assert "不存在的来源" in response.json()["detail"]


def test_scoped_retrieval_cannot_expand_other_document(env):
    app, client = env
    doc1 = upload(app, client, "a.md", "# 上海制度\n\n上海住宿标准为 500 元。")
    doc2 = upload(app, client, "b.md", "# 北京制度\n\n北京住宿标准为 600 元。")
    index(app, client, doc1)
    index(app, client, doc2)
    results = client.post("/api/search", json={"query": "北京住宿", "document_ids": [doc1]}).json()["results"]
    assert all(result["document_id"] == doc1 for result in results)
    foreign_chunk = app.state.knowledge.chunks(doc2)[0]["id"]
    assert app.state.knowledge.read_neighbors(foreign_chunk, [doc1]) == []


def test_missing_deepseek_configuration_is_explicit(tmp_path):
    app = create_app(Settings(data_dir=tmp_path, admin_password="Admin-test-123456"), TestEmbeddings())
    with TestClient(app) as client:
        client.post("/api/auth/login", json={"username": "admin", "password": "Admin-test-123456"})
        response = client.post("/api/chat", json={"question": "问题"})
        assert response.status_code == 503
        assert "DEEPSEEK_API_KEY" in response.json()["detail"]
        assert client.get("/api/overview").json()["models"]["llm"]["configured"] is False


def test_login_rate_limit(env):
    _, client = env
    for _ in range(11):
        assert client.post("/api/auth/login", json={"username": "nobody", "password": "incorrect"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "nobody", "password": "incorrect"}).status_code == 429


def test_chat_numbers_only_used_sources_and_keeps_real_chunk_ordinals(env):
    app, client = env
    doc_id = upload(app, client, "D10_信息系统.md", "# 信息系统\n\n第一条 账号必须审批。\n第二条 变更必须测试。\n第三条 数据必须备份。")
    chunks = app.state.knowledge.chunks(doc_id)
    assert len(chunks) == 3
    app.state.knowledge.search = lambda *_: [{**c, "filename": "D10_信息系统.md", "topic": "信息系统"} for c in chunks]
    original = app.state.agent.llm.complete

    async def reply(messages, tools=None, required=False):
        if messages[-1]["role"] == "user":
            return await original(messages, tools, required)
        return {"role": "assistant", "content": "备份[S3]，账号[S1]，再次备份[S3]。"}

    app.state.agent.llm.complete = reply
    response = client.post("/api/chat", json={"question": "账号和备份要求？"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["answer"] == "备份[S1]，账号[S2]，再次备份[S1]。"
    assert [c["ordinal"] for c in body["citations"]] == [3, 1]
    assert [c["chunk_id"] for c in body["citations"]] == [chunks[2]["id"], chunks[0]["id"]]
    history = client.get(f"/api/conversations/{body['conversation_id']}").json()
    assert history["messages"][-1]["citations"] == body["citations"]


def test_legacy_history_recovers_ordinal_without_rewriting_snapshot(env):
    app, client = env
    doc_id = upload(app, client)
    index(app, client, doc_id)
    body = client.post("/api/chat", json={"question": "住宿上限？"}).json()
    cid = body["conversation_id"]
    source = {k: v for k, v in body["citations"][0].items() if k != "ordinal"}
    source["id"] = "S4"
    snapshot = json.dumps([source], ensure_ascii=False)
    with app.state.db.connect() as conn:
        conn.execute("UPDATE messages SET content=?,citations=? WHERE conversation_id=? AND role='assistant'",
                     ("历史答案[S4]", snapshot, cid))
    message = client.get(f"/api/conversations/{cid}").json()["messages"][-1]
    assert message["content"] == "历史答案[S1]"
    assert message["citations"][0]["ordinal"] == 1
    stored = app.state.db.one("SELECT content,citations FROM messages WHERE conversation_id=? AND role='assistant'", (cid,))
    assert stored == {"content": "历史答案[S4]", "citations": snapshot}
    # A coincidental ID from another document must never supply a false ordinal.
    source["document_id"] = "other-document"
    with app.state.db.connect() as conn:
        conn.execute("UPDATE messages SET citations=? WHERE conversation_id=? AND role='assistant'",
                     (json.dumps([source]), cid))
    assert "ordinal" not in client.get(f"/api/conversations/{cid}").json()["messages"][-1]["citations"][0]
    client.delete(f"/api/documents/{doc_id}")
    message = client.get(f"/api/conversations/{cid}").json()["messages"][-1]
    assert "ordinal" not in message["citations"][0]
    assert message["citations"][0]["content"] == source["content"]
