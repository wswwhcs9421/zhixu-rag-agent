from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: ROOT / "data")
    admin_username: str = "admin"
    admin_password: str = ""
    cookie_secure: bool = False
    deepseek_url: str = "https://api.deepseek.com"
    deepseek_key: str = ""
    deepseek_model: str = ""
    bge_mode: str = "local"
    bge_model: str = "BAAI/bge-m3"
    bge_device: str = "cpu"
    bge_url: str = "http://127.0.0.1:8001/v1"
    bge_key: str = ""
    chunk_size: int = 1000
    chunk_overlap: int = 120
    max_upload_mb: int = 20
    max_agent_rounds: int = 3

    def __post_init__(self):
        self.data_dir = Path(self.data_dir).resolve()
        if self.bge_mode not in {"local", "api"}:
            raise ValueError("BGE_MODE must be local or api")
        if not 200 <= self.chunk_size <= 4000:
            raise ValueError("RAG_CHUNK_SIZE must be between 200 and 4000 characters")
        if not 0 <= self.chunk_overlap < self.chunk_size // 2:
            raise ValueError("RAG_CHUNK_OVERLAP must be less than half the chunk size")
        if not 1 <= self.max_agent_rounds <= 6:
            raise ValueError("RAG_MAX_AGENT_ROUNDS must be between 1 and 6")

    @property
    def embedding_key(self) -> str:
        endpoint = self.bge_url if self.bge_mode == "api" else "local"
        return hashlib.sha256(f"{endpoint}|{self.bge_model}|1024".encode()).hexdigest()[:24]

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(ROOT / ".env")
        return cls(
            data_dir=Path(os.getenv("RAG_DATA_DIR", str(ROOT / "data"))),
            admin_username=os.getenv("RAG_ADMIN_USERNAME", "admin"),
            admin_password=os.getenv("RAG_ADMIN_PASSWORD", ""),
            cookie_secure=os.getenv("RAG_COOKIE_SECURE", "false").lower() == "true",
            deepseek_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/"),
            deepseek_key=os.getenv("DEEPSEEK_API_KEY", ""),
            deepseek_model=os.getenv("DEEPSEEK_MODEL", ""),
            bge_mode=os.getenv("BGE_MODE", "local"),
            bge_model=os.getenv("BGE_MODEL", "BAAI/bge-m3"),
            bge_device=os.getenv("BGE_DEVICE", "cpu"),
            bge_url=os.getenv("BGE_BASE_URL", "http://127.0.0.1:8001/v1").rstrip("/"),
            bge_key=os.getenv("BGE_API_KEY", ""),
            chunk_size=int(os.getenv("RAG_CHUNK_SIZE", "1000")),
            chunk_overlap=int(os.getenv("RAG_CHUNK_OVERLAP", "120")),
            max_upload_mb=int(os.getenv("RAG_MAX_UPLOAD_MB", "20")),
            max_agent_rounds=int(os.getenv("RAG_MAX_AGENT_ROUNDS", "3")),
        )
