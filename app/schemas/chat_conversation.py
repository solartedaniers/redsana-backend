from datetime import datetime

from pydantic import BaseModel


class ChatConversationRead(BaseModel):
    id: str
    title: str | None
    updated_at: datetime


class ChatConversationRename(BaseModel):
    title: str


class ChatMessageRead(BaseModel):
    id: str
    role: str
    content: str
    created_at: datetime


class ChatSendMessageRequest(BaseModel):
    message: str


class ChatSendMessageResponse(BaseModel):
    reply: str
