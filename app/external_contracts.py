from decimal import Decimal
from typing import Literal, Protocol

from pydantic import BaseModel


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str


class PartnerIdentity(Protocol):
    async def login(self, login: str, password: str) -> TokenPair: ...

    async def refresh(self, login: str, refresh_token: str) -> TokenPair: ...


class TelegramUpdate(BaseModel):
    update_id: int
    message: dict | None = None
    callback_query: dict | None = None


class TelegramGateway(Protocol):
    async def feed_update(self, update: TelegramUpdate) -> None: ...

    async def send_message(self, chat_id: int, text: str) -> int: ...


class PaymentOrder(BaseModel):
    amount: Decimal
    currency: str
    return_url: str
    idempotency_key: str


class Payment(BaseModel):
    id: str
    status: str
    paid: bool
    confirmation_url: str | None = None


class PaymentEvent(BaseModel):
    type: Literal["notification"]
    event: str
    object: Payment


class PaymentGateway(Protocol):
    async def create_payment(self, order: PaymentOrder) -> Payment: ...

    async def check_payment_status(self, payment_id: str) -> Payment | None: ...

    def parse_webhook(self, request: bytes) -> PaymentEvent: ...


class Email(BaseModel):
    from_email: str
    from_name: str
    to: str
    subject: str
    text: str
    html: str


class MailGateway(Protocol):
    async def send_email(self, email: Email) -> str: ...


class TextPart(BaseModel):
    type: Literal["text"] = "text"
    text: str


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str | list[TextPart]


class ChatRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    stream: Literal[False] = False


class EmbeddingGateway(Protocol):
    async def create_embedding(self, text: str) -> list[float]: ...


class CompletionGateway(Protocol):
    async def get_response(self, prompt_query: str, system_prompt: str) -> str: ...


class MediaCompletionGateway(Protocol):
    async def get_response_with_image(self, prompt: str, image_data: bytes) -> str: ...

    async def get_response_with_audio(self, prompt: str, audio_data: bytes) -> str: ...
