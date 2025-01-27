from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class UserBase(BaseModel):
    username: str
    language: str

class UserCreate(UserBase):
    password: str

class User(UserBase):
    id: int

    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: Optional[str] = None

class MessageBase(BaseModel):
    receiver_id: int
    original_message: str

class MessageCreate(MessageBase):
    pass

class Message(MessageBase):
    id: int
    sender_id: int
    translated_message: str
    timestamp: datetime

    class Config:
        from_attributes = True