from __future__ import annotations

import importlib.util
import threading
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import numpy as np

from .config import Settings


class ProviderError(Exception):
    pass


class Embeddings:
    dimension = 1024

    def __init__(self, settings: Settings):
        self.settings = settings
        self.key = settings.embedding_key
        self._model = None
        self._lock = threading.Lock()

    def status(self):
        local = self.settings.bge_mode == "local"
        local_files = local and (Path(self.settings.bge_model) / "config.json").is_file()
        return {
            "mode": self.settings.bge_mode, "model": self.settings.bge_model,
            "dimension": self.dimension, "loaded": self._model is not None,
            "runtime_installed": not local or importlib.util.find_spec("sentence_transformers") is not None,
            "note": ("使用本地模型文件，首次使用时加载到内存" if local_files else "首次建立向量时会下载模型")
                    if local else "需要可用的 bge-m3 Embedding API",
        }

    def encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, self.dimension), dtype=np.float32)
        with self._lock:
            if self.settings.bge_mode == "local":
                if importlib.util.find_spec("sentence_transformers") is None:
                    raise ProviderError("本地 bge-m3 运行库尚未安装。请执行 .venv\\Scripts\\python.exe -m pip install -r requirements-local-model.txt，或配置 BGE_MODE=api。")
                if self._model is None:
                    try:
                        from sentence_transformers import SentenceTransformer
                        self._model = SentenceTransformer(
                            self.settings.bge_model, device=self.settings.bge_device,
                            cache_folder=str(self.settings.data_dir / "models"), trust_remote_code=False,
                        )
                    except Exception as exc:
                        raise ProviderError("bge-m3 加载失败，请检查模型下载、磁盘空间和设备配置。") from exc
                try:
                    values = self._model.encode(texts, normalize_embeddings=True, batch_size=8, show_progress_bar=False)
                except Exception as exc:
                    raise ProviderError("bge-m3 编码失败，请检查内存和模型配置。") from exc
            else:
                headers = {"Authorization": f"Bearer {self.settings.bge_key}"} if self.settings.bge_key else {}
                try:
                    with httpx.Client(timeout=120) as client:
                        response = client.post(self.settings.bge_url + "/embeddings", headers=headers,
                                               json={"model": self.settings.bge_model, "input": texts})
                        response.raise_for_status()
                        data = sorted(response.json()["data"], key=lambda item: item["index"])
                        if [item["index"] for item in data] != list(range(len(texts))):
                            raise ValueError("Invalid embedding indices")
                        values = [item["embedding"] for item in data]
                except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                    raise ProviderError("Embedding API 调用失败，请检查 BGE_BASE_URL、BGE_MODEL、密钥及服务日志。") from exc
        arr = np.asarray(values, dtype=np.float32)
        if arr.shape != (len(texts), self.dimension) or not np.isfinite(arr).all():
            raise ProviderError("bge-m3 应返回每段 1024 维的有限数值向量，API 返回格式不符合要求。")
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        if (norms < 1e-10).any():
            raise ProviderError("Embedding 服务返回了无效的零向量。")
        return arr / norms


class DeepSeek:
    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def configured(self):
        return bool(self.settings.deepseek_key and self.settings.deepseek_model)

    async def complete(self, messages: list[dict], tools: list[dict] | None = None, required=False):
        if not self.configured:
            raise ProviderError("尚未配置 DeepSeek。请在 .env 中设置 DEEPSEEK_API_KEY 和供应商实际提供的 DEEPSEEK_MODEL，然后重启服务。")
        body = {"model": self.settings.deepseek_model, "messages": messages, "temperature": 0.1, "max_tokens": 2500}
        if urlsplit(self.settings.deepseek_url).hostname == "api.deepseek.com":
            # Official V4 Flash enables thinking by default, which rejects the
            # required tool choice used to guarantee a fresh knowledge search.
            # Keep the whole tool conversation in non-thinking mode; do not
            # impose this provider-specific option on third-party endpoints.
            body["thinking"] = {"type": "disabled"}
        if tools:
            body.update(tools=tools, tool_choice="required" if required else "auto")
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(60, connect=15)) as client:
                response = await client.post(
                    self.settings.deepseek_url + "/chat/completions", json=body,
                    headers={"Authorization": f"Bearer {self.settings.deepseek_key}"},
                )
                response.raise_for_status()
                message = response.json()["choices"][0]["message"]
                if not isinstance(message, dict):
                    raise ValueError("Invalid response")
                return {key: value for key, value in message.items()
                        if key in {"role", "content", "tool_calls", "reasoning_content"}}
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            raise ProviderError(f"DeepSeek API 返回 HTTP {code}。请检查模型 ID、密钥、额度及该模型的工具调用支持。") from exc
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError("DeepSeek API 连接失败或响应格式异常，请检查服务地址和网络。") from exc
