import time

from fastapi import FastAPI

from app.external_contracts import ChatRequest

app = FastAPI(title="Demo Chat Completions API")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/chat/completions")
def complete(request: ChatRequest):
    return {
        "id": "chatcmpl-demo",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": request.model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "Demo completion."},
                "finish_reason": "stop",
            }
        ],
    }
