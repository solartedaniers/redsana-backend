from pydantic import BaseModel


class SecurityChatRequest(BaseModel):
    message: str


class SecurityChatResponse(BaseModel):
    reply: str
