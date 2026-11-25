from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.models.finance import Base, utc_now


class ChatThread(Base):
    __tablename__ = "chat_threads"
    __table_args__ = (CheckConstraint("decision IN ('CONFIRM', 'CANCEL')"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    decision: Mapped[str | None] = mapped_column(String(7))
    receipt: Mapped[dict | None] = mapped_column(JSON)


class ChatConversation(Base):
    __tablename__ = "chat_conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(36), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    updated_at: Mapped[datetime | None] = mapped_column(default=utc_now)


class DeletedChatCheckpoint(Base):
    __tablename__ = "deleted_chat_checkpoints"
    thread_id: Mapped[str] = mapped_column(String(36), primary_key=True)


class ChatTurn(Base):
    __tablename__ = "chat_turns"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("chat_conversations.id"), index=True)
    thread_id: Mapped[str] = mapped_column(ForeignKey("chat_threads.id"), unique=True)
    message: Mapped[str]
    response: Mapped[dict | None] = mapped_column(JSON(none_as_null=True))
    intent: Mapped[str | None] = mapped_column(String(24))
