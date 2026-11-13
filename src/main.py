"""LunAI: MVP de pergunta sobre imagem com adaptadores de modelo configuráveis."""
from __future__ import annotations

import base64
import binascii
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from collections import deque
from threading import Lock
from time import monotonic

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("lunai")

STATIC_DIR = Path(__file__).parent / "static"
ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "10"))
MAX_QUESTION_CHARS = int(os.getenv("MAX_QUESTION_CHARS", "2000"))
if not 1 <= MAX_UPLOAD_MB <= 20:
    raise RuntimeError("MAX_UPLOAD_MB precisa estar entre 1 e 20.")
if not 1 <= MAX_QUESTION_CHARS <= 10000:
    raise RuntimeError("MAX_QUESTION_CHARS precisa estar entre 1 e 10000.")


@dataclass(frozen=True)
class ModelSettings:
    provider: str
    api_key: str
    model: str
    base_url: str
    timeout_seconds: float
    max_output_tokens: int


class VisionProvider(Protocol):
    async def answer(self, question: str, image: bytes, media_type: str) -> str: ...


class OpenAICompatibleProvider:
    """Adaptador da API OpenAI Images + Responses. Sem registrar prompts ou imagem."""

    def __init__(self, settings: ModelSettings) -> None:
        self.settings = settings

    async def answer(self, question: str, image: bytes, media_type: str) -> str:
        image_url = f"data:{media_type};base64,{base64.b64encode(image).decode('ascii')}"
        payload = {
            "model": self.settings.model,
            "input": [{
                "role": "user",
                "content": [
                    {"type": "input_text", "text": question},
                    {"type": "input_image", "image_url": image_url, "detail": "auto"},
                ],
            }],
            "max_output_tokens": self.settings.max_output_tokens,
        }
        headers = {"Authorization": f"Bearer {self.settings.api_key}"}
        try:
            async with httpx.AsyncClient(timeout=self.settings.timeout_seconds) as client:
                response = await client.post(
                    f"{self.settings.base_url.rstrip('/')}/responses",
                    headers=headers,
                    json=payload,
                )
            if response.status_code in (401, 403):
                logger.warning("Provedor recusou autenticação (HTTP %s).", response.status_code)
                raise HTTPException(status_code=502, detail="Falha de autenticação no provedor de IA.")
            if response.status_code == 429:
                raise HTTPException(status_code=503, detail="Limite temporário do provedor atingido. Tente novamente.")
            if response.status_code >= 500:
                raise HTTPException(status_code=502, detail="O provedor de IA está temporariamente indisponível.")
            if response.is_error:
                logger.warning("Provedor retornou erro HTTP %s.", response.status_code)
                raise HTTPException(status_code=502, detail="O provedor não aceitou a solicitação.")
            body = response.json()
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="O provedor demorou demais para responder.") from None
        except httpx.RequestError:
            logger.warning("Falha de conexão com provedor de IA.")
            raise HTTPException(status_code=502, detail="Não foi possível conectar ao provedor de IA.") from None
        except ValueError:
            logger.warning("Resposta inválida do provedor de IA.")
            raise HTTPException(status_code=502, detail="O provedor retornou uma resposta inválida.") from None

        # Responses API tem output_text no SDK; na REST extraímos apenas blocos de texto.
        chunks: list[str] = []
        for item in body.get("output", []):
            for part in item.get("content", []):
                if part.get("type") == "output_text" and isinstance(part.get("text"), str):
                    chunks.append(part["text"])
        answer = "\n".join(chunks).strip()
        if not answer:
            logger.warning("Provedor concluiu sem texto de resposta.")
            raise HTTPException(status_code=502, detail="O modelo não retornou uma resposta em texto.")
        return answer


class OllamaProvider:
    """Adaptador opcional para Ollama local (API /api/chat)."""

    def __init__(self, settings: ModelSettings) -> None:
        self.settings = settings

    async def answer(self, question: str, image: bytes, media_type: str) -> str:
        payload = {
            "model": self.settings.model,
            "stream": False,
            "messages": [{"role": "user", "content": question,
                          "images": [base64.b64encode(image).decode("ascii")]}],
            "options": {"num_predict": self.settings.max_output_tokens},
        }
        try:
            async with httpx.AsyncClient(timeout=self.settings.timeout_seconds) as client:
                response = await client.post(f"{self.settings.base_url.rstrip('/')}/api/chat", json=payload)
            if response.status_code == 404:
                raise HTTPException(status_code=503, detail="Modelo Ollama não encontrado. Baixe o modelo configurado.")
            if response.is_error:
                logger.warning("Ollama retornou erro HTTP %s.", response.status_code)
                raise HTTPException(status_code=502, detail="O servidor Ollama não aceitou a solicitação.")
            answer = response.json().get("message", {}).get("content", "").strip()
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="O modelo local demorou demais para responder.") from None
        except httpx.RequestError:
            logger.warning("Falha de conexão com Ollama.")
            raise HTTPException(status_code=502, detail="Não foi possível conectar ao Ollama local.") from None
        except ValueError:
            logger.warning("Resposta inválida do Ollama.")
            raise HTTPException(status_code=502, detail="O servidor Ollama retornou resposta inválida.") from None
        if not answer:
            raise HTTPException(status_code=502, detail="O modelo não retornou uma resposta em texto.")
        return answer


def create_provider() -> VisionProvider | None:
    provider_name = os.getenv("MODEL_PROVIDER", "").strip().lower()
    if not provider_name:
        return None
    model = os.getenv("MODEL_NAME", "").strip()
    if not model or len(model) > 128:
        raise RuntimeError("Defina MODEL_NAME (até 128 caracteres) para o provedor escolhido.")
    try:
        timeout = float(os.getenv("MODEL_TIMEOUT_SECONDS", "60"))
        max_tokens = int(os.getenv("MODEL_MAX_OUTPUT_TOKENS", "500"))
    except ValueError as exc:
        raise RuntimeError("Timeout e limite de tokens devem ser números válidos.") from exc
    if not 1 <= timeout <= 300:
        raise RuntimeError("MODEL_TIMEOUT_SECONDS precisa estar entre 1 e 300.")
    if not 1 <= max_tokens <= 4096:
        raise RuntimeError("MODEL_MAX_OUTPUT_TOKENS precisa estar entre 1 e 4096.")
    if provider_name == "openai":
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("Defina OPENAI_API_KEY no ambiente para usar o provedor OpenAI.")
        base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").strip()
        if not base_url.startswith("https://"):
            raise RuntimeError("OPENAI_BASE_URL precisa usar HTTPS.")
        settings = ModelSettings(provider_name, api_key, model, base_url, timeout, max_tokens)
        return OpenAICompatibleProvider(settings)
    if provider_name == "ollama":
        base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").strip()
        if not (base_url.startswith("http://127.0.0.1") or base_url.startswith("http://localhost") or base_url.startswith("https://")):
            raise RuntimeError("OLLAMA_BASE_URL deve apontar para localhost ou HTTPS.")
        settings = ModelSettings(provider_name, "", model, base_url, timeout, max_tokens)
        return OllamaProvider(settings)
    raise RuntimeError("MODEL_PROVIDER aceito: openai ou ollama.")


provider = create_provider()
app = FastAPI(title="LunAI", description="Pergunte em português sobre uma imagem", version="0.2.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Limitador em memória para execução local/uma instância. Atrás de proxy, configure
# trusted proxy headers e use rate limiting compartilhado (ex.: Redis) para produção.
RATE_LIMIT_REQUESTS = int(os.getenv("RATE_LIMIT_REQUESTS", "10"))
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
if not 1 <= RATE_LIMIT_REQUESTS <= 1000 or not 1 <= RATE_LIMIT_WINDOW_SECONDS <= 86400:
    raise RuntimeError("RATE_LIMIT_REQUESTS deve ser 1..1000 e RATE_LIMIT_WINDOW_SECONDS 1..86400.")
_request_history: dict[str, deque[float]] = {}
_request_history_lock = Lock()


def check_rate_limit(client_key: str) -> int | None:
    """Retorna segundos até liberar ou None quando o pedido pode seguir."""
    now = monotonic()
    cutoff = now - RATE_LIMIT_WINDOW_SECONDS
    with _request_history_lock:
        history = _request_history.setdefault(client_key, deque())
        while history and history[0] <= cutoff:
            history.popleft()
        if len(history) >= RATE_LIMIT_REQUESTS:
            return max(1, int(history[0] + RATE_LIMIT_WINDOW_SECONDS - now + 0.999))
        history.append(now)
    return None


@app.get("/")
def home():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health():
    return {"status": "ok", "provider_configured": provider is not None}


@app.post("/api/ask")
async def ask(request: Request, question: str = Form(...), image: UploadFile = File(...)):
    retry_after = check_rate_limit(request.client.host if request.client else "unknown")
    if retry_after is not None:
        raise HTTPException(
            status_code=429,
            detail="Muitas solicitações. Aguarde um pouco e tente novamente.",
            headers={"Retry-After": str(retry_after)},
        )
    question = question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Escreva uma pergunta sobre a imagem.")
    if len(question) > MAX_QUESTION_CHARS:
        raise HTTPException(status_code=413, detail=f"A pergunta deve ter até {MAX_QUESTION_CHARS} caracteres.")
    media_type = (image.content_type or "").split(";")[0].strip().lower()
    if media_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=415, detail="Envie uma imagem JPG, PNG ou WebP.")

    try:
        data = await image.read(MAX_UPLOAD_MB * 1024 * 1024 + 1)
    finally:
        await image.close()
    if not data:
        raise HTTPException(status_code=400, detail="O arquivo enviado está vazio.")
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"A imagem deve ter até {MAX_UPLOAD_MB} MB.")
    # Confira assinatura MIME além do content-type fornecido pelo cliente.
    signatures = {"image/jpeg": (b"\xff\xd8\xff",), "image/png": (b"\x89PNG\r\n\x1a\n",),
                  "image/webp": (b"RIFF",)}
    valid_signature = data.startswith(signatures[media_type])
    if media_type == "image/webp":
        valid_signature = valid_signature and data[8:12] == b"WEBP"
    if not valid_signature:
        raise HTTPException(status_code=415, detail="O conteúdo não corresponde ao formato de imagem informado.")
    if provider is None:
        return {"answer": "A imagem foi recebida. Configure um provedor em .env para gerar uma resposta real.",
                "status": "provider_not_configured"}
    answer = await provider.answer(question, data, media_type)
    return {"answer": answer, "status": "ok"}
