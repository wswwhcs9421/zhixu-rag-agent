from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
import sqlite3
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from typing import Literal
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from .agent import RagAgent
from .citations import number_citations
from .config import ROOT, Settings
from .db import Database
from .knowledge import Knowledge
from .providers import DeepSeek, Embeddings, ProviderError
from .security import hash_password, now, token_hash, uid, verify_password

log = logging.getLogger(__name__)
COOKIE = "rag_session"


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Login(Input):
    username: str = Field(min_length=1, max_length=40)
    password: str = Field(min_length=1, max_length=256)


class NewUser(Input):
    username: str = Field(pattern=r"^[a-zA-Z0-9_.@-]{3,40}$")
    password: str = Field(min_length=12, max_length=256)
    role: Literal["admin", "reader"] = "reader"


class ChangeUser(Input):
    role: Literal["admin", "reader"] | None = None
    active: bool | None = None
    password: str | None = Field(default=None, min_length=12, max_length=256)


class Password(Input):
    old_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


class Topic(Input):
    topic: str = Field(min_length=1, max_length=160)


class ChunkContent(Input):
    content: str = Field(min_length=1, max_length=4000)


class Search(Input):
    query: str = Field(min_length=1, max_length=1000)
    document_ids: list[str] = Field(default_factory=list, max_length=50)


class Chat(Input):
    question: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = None
    document_ids: list[str] = Field(default_factory=list, max_length=50)


def create_app(settings: Settings | None = None, embeddings=None, llm=None):
    settings = settings or Settings.from_env()
    db = Database(settings.data_dir / "rag.sqlite3")
    if not db.one("SELECT id FROM users LIMIT 1"):
        if not re.fullmatch(r"[a-zA-Z0-9_.@-]{3,40}", settings.admin_username):
            raise ValueError("管理员用户名须为 3～40 位英文字母、数字或 _.@-")
        password = settings.admin_password or secrets.token_urlsafe(18)
        if not 12 <= len(password) <= 256:
            raise ValueError("RAG_ADMIN_PASSWORD 至少需要 12 个字符，最多 256 个字符。")
        with db.connect() as conn:
            conn.execute("INSERT INTO users(id,username,password_hash,role,created_at) VALUES(?,?,?,?,?)",
                         (uid(), settings.admin_username, hash_password(password), "admin", now()))
        if not settings.admin_password:
            credentials = settings.data_dir / "bootstrap-admin.txt"
            credentials.write_text(f"首次管理员账号：{settings.admin_username}\n首次密码：{password}\n登录后请在账号菜单中修改密码；修改后本文件会自动移除。\n", encoding="utf-8")
            log.warning("Initial administrator credentials saved to %s", credentials)
    with db.connect() as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (time.time(),))
    embeddings = embeddings or Embeddings(settings)
    llm = llm or DeepSeek(settings)
    knowledge = Knowledge(db, settings, embeddings)
    agent = RagAgent(knowledge, llm, settings.max_agent_rounds)
    chat_locks = set()
    attempts = defaultdict(deque)
    attempt_lock = threading.Lock()
    dummy_hash = hash_password(secrets.token_urlsafe(20))

    @asynccontextmanager
    async def lifespan(app):
        yield
        knowledge.executor.shutdown(wait=True, cancel_futures=True)

    app = FastAPI(title="知序 · RAG Agent", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.db, app.state.knowledge, app.state.settings = db, knowledge, settings
    app.state.agent = agent

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if origin:
                parsed = urlsplit(origin)
                if parsed.scheme not in {"http", "https"} or parsed.netloc != request.headers.get("host") or parsed.scheme != request.url.scheme:
                    return JSONResponse({"detail": "拒绝来自其他站点的写入请求。"}, status_code=403)
            if request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"detail": "拒绝跨站请求。"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def current_user(request: Request):
        token = request.cookies.get(COOKIE, "")
        if not token:
            raise HTTPException(401, "请先登录。")
        user = db.one("""SELECT u.id,u.username,u.role,u.active FROM sessions s JOIN users u ON u.id=s.user_id
            WHERE s.token_hash=? AND s.expires_at>? AND u.active=1""", (token_hash(token), time.time()))
        if not user:
            raise HTTPException(401, "登录已过期或账号已停用，请重新登录。")
        return user

    def admin(user=Depends(current_user)):
        if user["role"] != "admin":
            raise HTTPException(403, "此操作仅允许管理员执行。")
        return user

    def document(document_id):
        row = db.one("SELECT * FROM documents WHERE id=?", (document_id,))
        if not row:
            raise HTTPException(404, "文档不存在。")
        return row

    def writable_document(document_id):
        row = document(document_id)
        if knowledge.busy(document_id):
            raise HTTPException(409, "文档正在处理中，请稍后再修改。")
        return row

    def audit(conn, user, action, target=""):
        conn.execute("INSERT INTO audit(user_id,action,target,created_at) VALUES(?,?,?,?)", (user["id"], action, target, now()))

    def invalidate(conn, document_id):
        conn.execute("UPDATE documents SET status='parsed',error='',revision=revision+1,updated_at=? WHERE id=?", (now(), document_id))

    def validate_scope(document_ids):
        for document_id in document_ids:
            document(document_id)

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.post("/api/auth/login")
    def login(payload: Login, request: Request, response: Response):
        address = request.client.host if request.client else "unknown"
        with attempt_lock:
            queue = attempts[address]
            while queue and queue[0] < time.monotonic() - 60:
                queue.popleft()
            if len(queue) >= 12:
                raise HTTPException(429, "登录尝试过于频繁，请一分钟后重试。")
            queue.append(time.monotonic())
        user = db.one("SELECT * FROM users WHERE username=?", (payload.username,))
        matched = verify_password(payload.password, user["password_hash"] if user else dummy_hash)
        if not user or not matched or not user["active"]:
            raise HTTPException(401, "用户名或密码错误，或账号已停用。")
        token = secrets.token_urlsafe(32)
        with db.connect() as conn:
            conn.execute("INSERT INTO sessions(token_hash,user_id,expires_at) VALUES(?,?,?)", (token_hash(token), user["id"], time.time() + 28800))
            audit(conn, user, "login")
        response.set_cookie(COOKIE, token, httponly=True, secure=settings.cookie_secure, samesite="strict", max_age=28800)
        return {key: user[key] for key in ("id", "username", "role")}

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response):
        with db.connect() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash(request.cookies.get(COOKIE, "")),))
        response.delete_cookie(COOKIE)
        return {"ok": True}

    @app.get("/api/auth/me")
    def me(user=Depends(current_user)):
        return user

    @app.post("/api/auth/password")
    def password(payload: Password, response: Response, user=Depends(current_user)):
        row = db.one("SELECT password_hash FROM users WHERE id=?", (user["id"],))
        if not verify_password(payload.old_password, row["password_hash"]):
            raise HTTPException(400, "当前密码不正确。")
        with db.connect() as conn:
            conn.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(payload.new_password), user["id"]))
            conn.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
            audit(conn, user, "change_password")
        if user["username"] == settings.admin_username:
            (settings.data_dir / "bootstrap-admin.txt").unlink(missing_ok=True)
        response.delete_cookie(COOKIE)
        return {"ok": True}

    @app.get("/api/overview")
    def overview(user=Depends(current_user)):
        docs = knowledge.list_documents()
        for doc in docs:
            if doc["status"] == "ready" and doc["vector_count"] < doc["chunk_count"]:
                doc["status"] = "parsed"
                doc["error"] = "当前 Embedding 配置已变化，请重新建立向量。"
        counts = {"documents": len(docs), "parsed": sum(d["chunk_count"] > 0 for d in docs),
                  "chunks": sum(d["chunk_count"] for d in docs), "vectors": sum(d["vector_count"] for d in docs)}
        models = {"llm": {"configured": llm.configured, "model": settings.deepseek_model or "DeepSeek V4 · 待配置"},
                  "embedding": embeddings.status()}
        safe_docs = [{k: v for k, v in doc.items() if k not in {"stored_name", "created_by"}} for doc in docs]
        return {"counts": counts, "documents": safe_docs, "models": models, "max_upload_mb": settings.max_upload_mb}

    @app.get("/api/documents/{document_id}/chunks")
    def list_chunks(document_id: str, user=Depends(current_user)):
        document(document_id)
        return knowledge.chunks(document_id)

    @app.post("/api/documents", status_code=201)
    async def upload(file: UploadFile = File(...), user=Depends(admin)):
        filename = (file.filename or "").replace("\\", "/").split("/")[-1][:200]
        suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if suffix not in {".pdf", ".txt", ".md", ".markdown"}:
            raise HTTPException(400, "初版支持 PDF、TXT、MD 和 Markdown 文件。")
        document_id = uid()
        stored_name = document_id + suffix
        path = knowledge.upload_dir / stored_name
        byte_size = 0
        try:
            with path.open("xb") as stream:
                while block := await file.read(1024 * 1024):
                    byte_size += len(block)
                    if byte_size > settings.max_upload_mb * 1024 * 1024:
                        raise HTTPException(413, f"单个文件最多 {settings.max_upload_mb} MB。")
                    stream.write(block)
            if not byte_size:
                raise HTTPException(400, "不能上传空文件。")
            with db.connect() as conn:
                conn.execute("""INSERT INTO documents(id,filename,topic,stored_name,byte_size,created_at,updated_at,created_by)
                    VALUES(?,?,?,?,?,?,?,?)""", (document_id, filename, filename.rsplit(".", 1)[0], stored_name, byte_size, now(), now(), user["id"]))
                audit(conn, user, "upload_document", document_id)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        finally:
            await file.close()
        knowledge.schedule(document_id, "parse")
        return {"id": document_id, "status": "queued"}

    @app.patch("/api/documents/{document_id}")
    def edit_document(document_id: str, payload: Topic, user=Depends(admin)):
        writable_document(document_id)
        if not payload.topic.strip():
            raise HTTPException(400, "主题不能为空。")
        with db.connect() as conn:
            conn.execute("UPDATE documents SET topic=?,updated_at=? WHERE id=?", (payload.topic.strip(), now(), document_id))
            audit(conn, user, "edit_topic", document_id)
        return {"ok": True}

    @app.delete("/api/documents/{document_id}")
    def delete_document(document_id: str, user=Depends(admin)):
        doc = writable_document(document_id)
        with db.connect() as conn:
            conn.execute("DELETE FROM documents WHERE id=?", (document_id,))
            audit(conn, user, "delete_document", document_id)
        (knowledge.upload_dir / doc["stored_name"]).unlink(missing_ok=True)
        return {"ok": True}

    def process_document(document_id, operation, user):
        document(document_id)
        try:
            knowledge.schedule(document_id, operation)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        with db.connect() as conn:
            audit(conn, user, "document_" + operation, document_id)
        return {"ok": True}

    @app.post("/api/documents/{document_id}/parse")
    def reparse_document(document_id: str, user=Depends(admin)):
        return process_document(document_id, "parse", user)

    @app.post("/api/documents/{document_id}/index")
    def index_document(document_id: str, user=Depends(admin)):
        return process_document(document_id, "index", user)

    @app.post("/api/documents/{document_id}/chunks", status_code=201)
    def add_chunk(document_id: str, payload: ChunkContent, user=Depends(admin)):
        writable_document(document_id)
        if not payload.content.strip():
            raise HTTPException(400, "片段不能为空。")
        chunk_id = uid()
        with db.connect() as conn:
            ordinal = conn.execute("SELECT COALESCE(MAX(ordinal),0)+1 FROM chunks WHERE document_id=?", (document_id,)).fetchone()[0]
            conn.execute("INSERT INTO chunks(id,document_id,ordinal,content,section) VALUES(?,?,?,?,?)", (chunk_id, document_id, ordinal, payload.content.strip(), "手动添加"))
            invalidate(conn, document_id)
            audit(conn, user, "add_chunk", chunk_id)
        return {"id": chunk_id}

    @app.patch("/api/chunks/{chunk_id}")
    def edit_chunk(chunk_id: str, payload: ChunkContent, user=Depends(admin)):
        chunk = db.one("SELECT * FROM chunks WHERE id=?", (chunk_id,))
        if not chunk:
            raise HTTPException(404, "片段不存在。")
        writable_document(chunk["document_id"])
        if not payload.content.strip():
            raise HTTPException(400, "片段不能为空。")
        with db.connect() as conn:
            conn.execute("UPDATE chunks SET content=? WHERE id=?", (payload.content.strip(), chunk_id))
            conn.execute("DELETE FROM vectors WHERE chunk_id=?", (chunk_id,))
            invalidate(conn, chunk["document_id"])
            audit(conn, user, "edit_chunk", chunk_id)
        return {"ok": True}

    @app.delete("/api/chunks/{chunk_id}")
    def delete_chunk(chunk_id: str, user=Depends(admin)):
        chunk = db.one("SELECT * FROM chunks WHERE id=?", (chunk_id,))
        if not chunk:
            raise HTTPException(404, "片段不存在。")
        writable_document(chunk["document_id"])
        with db.connect() as conn:
            conn.execute("DELETE FROM chunks WHERE id=?", (chunk_id,))
            invalidate(conn, chunk["document_id"])
            audit(conn, user, "delete_chunk", chunk_id)
        return {"ok": True}

    @app.post("/api/search")
    def search(payload: Search, user=Depends(current_user)):
        validate_scope(payload.document_ids)
        try:
            return {"results": knowledge.search(payload.query, payload.document_ids)}
        except ProviderError as exc:
            raise HTTPException(503, str(exc)) from exc

    @app.get("/api/conversations")
    def conversations(user=Depends(current_user)):
        return db.rows("SELECT * FROM conversations WHERE user_id=? ORDER BY created_at DESC LIMIT 50", (user["id"],))

    def owned_conversation(conversation_id, user):
        conversation = db.one("SELECT * FROM conversations WHERE id=? AND user_id=?", (conversation_id, user["id"]))
        if not conversation:
            raise HTTPException(404, "会话不存在。")
        return conversation

    @app.get("/api/conversations/{conversation_id}")
    def conversation_messages(conversation_id: str, user=Depends(current_user)):
        conversation = owned_conversation(conversation_id, user)
        messages = db.rows("SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at,id", (conversation_id,))
        for message in messages:
            message["citations"] = json.loads(message["citations"])
            message["trace"] = json.loads(message["trace"])
            if message["role"] == "assistant":
                for source in message["citations"]:
                    if source.get("ordinal") is None:
                        chunk = db.one("SELECT ordinal FROM chunks WHERE id=? AND document_id=?",
                                       (source.get("chunk_id"), source.get("document_id")))
                        if chunk:
                            source["ordinal"] = chunk["ordinal"]
                message["content"], message["citations"] = number_citations(
                    message["content"], message["citations"], strict=False)
        return {"conversation": conversation, "messages": messages}

    @app.post("/api/chat")
    async def chat(payload: Chat, user=Depends(current_user)):
        if not payload.question.strip():
            raise HTTPException(400, "问题不能为空。")
        validate_scope(payload.document_ids)
        conversation_id = payload.conversation_id
        if conversation_id:
            owned_conversation(conversation_id, user)
        else:
            conversation_id = uid()
            with db.connect() as conn:
                conn.execute("INSERT INTO conversations(id,user_id,title,created_at) VALUES(?,?,?,?)", (conversation_id, user["id"], payload.question.strip()[:60], now()))
        if conversation_id in chat_locks:
            raise HTTPException(409, "这个会话正在回答中，请稍后再发送。")
        # No await between check and insertion; all chat requests share one event loop.
        chat_locks.add(conversation_id)
        history = db.rows("SELECT role,content FROM messages WHERE conversation_id=? AND is_error=0 ORDER BY created_at DESC,id DESC LIMIT 10", (conversation_id,))[::-1]
        try:
            with db.connect() as conn:
                conn.execute("INSERT INTO messages(id,conversation_id,role,content,created_at) VALUES(?,?,?,?,?)", (uid(), conversation_id, "user", payload.question.strip(), now()))
            try:
                result = await agent.run(payload.question.strip(), history, payload.document_ids)
            except (ProviderError, TimeoutError) as exc:
                detail = str(exc) if isinstance(exc, ProviderError) else "本次问答超过 180 秒，请稍后重试或简化问题。"
                with db.connect() as conn:
                    conn.execute("INSERT INTO messages(id,conversation_id,role,content,is_error,created_at) VALUES(?,?,?,?,1,?)", (uid(), conversation_id, "assistant", detail, now()))
                return JSONResponse({"detail": detail, "conversation_id": conversation_id}, status_code=503)
            with db.connect() as conn:
                conn.execute("INSERT INTO messages(id,conversation_id,role,content,citations,trace,created_at) VALUES(?,?,?,?,?,?,?)",
                             (uid(), conversation_id, "assistant", result["answer"], json.dumps(result["citations"], ensure_ascii=False), json.dumps(result["trace"], ensure_ascii=False), now()))
                audit(conn, user, "query_knowledge", conversation_id)
            return {"conversation_id": conversation_id, **result}
        finally:
            chat_locks.discard(conversation_id)

    @app.get("/api/users")
    def users(user=Depends(admin)):
        return db.rows("SELECT id,username,role,active,created_at FROM users ORDER BY created_at")

    @app.post("/api/users", status_code=201)
    def new_user(payload: NewUser, user=Depends(admin)):
        user_id = uid()
        try:
            with db.connect() as conn:
                conn.execute("INSERT INTO users(id,username,password_hash,role,created_at) VALUES(?,?,?,?,?)", (user_id, payload.username, hash_password(payload.password), payload.role, now()))
                audit(conn, user, "create_user", user_id)
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, "用户名已存在。") from exc
        return {"id": user_id}

    @app.patch("/api/users/{user_id}")
    def update_user(user_id: str, payload: ChangeUser, user=Depends(admin)):
        if user_id == user["id"]:
            raise HTTPException(400, "不能在用户管理中修改自己的权限、状态或密码；修改密码请使用账号菜单。")
        with db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            target = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            if not target:
                raise HTTPException(404, "用户不存在。")
            role = payload.role if payload.role is not None else target["role"]
            active = int(payload.active) if payload.active is not None else target["active"]
            count = conn.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1").fetchone()[0]
            if target["role"] == "admin" and target["active"] and (role != "admin" or not active) and count <= 1:
                raise HTTPException(400, "必须保留至少一位启用的管理员。")
            conn.execute("UPDATE users SET role=?,active=? WHERE id=?", (role, active, user_id))
            if payload.password:
                conn.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(payload.password), user_id))
            conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
            audit(conn, user, "update_user", user_id)
        return {"ok": True}

    @app.delete("/api/users/{user_id}")
    def delete_user(user_id: str, user=Depends(admin)):
        if user_id == user["id"]:
            raise HTTPException(400, "不能删除当前登录的管理员。")
        with db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            target = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            if not target:
                raise HTTPException(404, "用户不存在。")
            count = conn.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1").fetchone()[0]
            if target["role"] == "admin" and target["active"] and count <= 1:
                raise HTTPException(400, "必须保留至少一位启用的管理员。")
            conn.execute("DELETE FROM users WHERE id=?", (user_id,))
            audit(conn, user, "delete_user", user_id)
        return {"ok": True}

    @app.get("/api/audit")
    def audit_log(user=Depends(admin)):
        return db.rows("SELECT a.*,u.username FROM audit a LEFT JOIN users u ON u.id=a.user_id ORDER BY a.id DESC LIMIT 100")

    @app.get("/")
    def index():
        return FileResponse(ROOT / "web" / "index.html", headers={"Cache-Control": "no-cache"})

    app.mount("/static", StaticFiles(directory=ROOT / "web"), name="static")
    return app
