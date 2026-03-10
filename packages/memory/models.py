import uuid
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import String, DateTime, Text, ForeignKey, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from packages.shared.db import Base

def gen_uuid() -> str:
    return str(uuid.uuid4())

def now_utc() -> datetime:
    return datetime.now(timezone.utc)

class ChatThread(Base):
    __tablename__ = "chat_threads"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    title: Mapped[str] = mapped_column(String, default="New Chat")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)

    # Relationship to messages
    messages: Mapped[list["ChatMessage"]] = relationship(
        "ChatMessage", 
        back_populates="thread", 
        cascade="all, delete-orphan",
        order_by="ChatMessage.timestamp"
    )

class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    thread_id: Mapped[str] = mapped_column(String, ForeignKey("chat_threads.id", ondelete="CASCADE"), index=True)
    
    role: Mapped[str] = mapped_column(String) # 'user' or 'assistant'
    content: Mapped[str] = mapped_column(Text)
    
    model_used: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    memory_used: Mapped[bool] = mapped_column(Boolean, default=False)
    
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    # Relationship back to thread
    thread: Mapped["ChatThread"] = relationship("ChatThread", back_populates="messages")
