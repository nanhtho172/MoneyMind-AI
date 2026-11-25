import sqlite3
from datetime import UTC, datetime
from threading import Lock
from uuid import UUID, uuid4

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command, StateSnapshot
from langsmith import tracing_context
from sqlalchemy import delete, func, or_, select, text, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from backend.app.agent.guardrails import sanitize
from backend.app.agent.llm import ChatCompletionsLLM, LLM
from backend.app.agent.rag import ChromaKnowledge, Retriever
from backend.app.agent.transaction_dialogue import TransactionWork
from backend.app.agent.workflow import PENDING_ADAPTER, build_workflow
from backend.app.core.calendar import local_now
from backend.app.core.config import Settings
from backend.app.core.observability import LangSmithTrace, current_trace_id, observe, trace_scope
from backend.app.models.chat import ChatConversation, ChatThread, ChatTurn, DeletedChatCheckpoint
from backend.app.models.finance import utc_now
from backend.app.schemas.chat import (
    ChatResponse, ConversationHistory, ConversationItem, ConversationPage, ConversationTurn, Decision, PendingTransaction,
)

CONTEXT_TURNS = 8
HISTORY_TURNS = 50
ACTIVE_PHASES = {"collecting", "ready_for_confirmation"}
TurnRecord = tuple[ChatTurn, ChatThread]


class ThreadNotFound(Exception):
    pass


class ThreadConflict(Exception):
    pass


class ConversationNotFound(Exception):
    pass


class ChatRuntime:
    def __init__(self, engine: Engine, settings: Settings, llm: LLM | None, retriever: Retriever | None):
        self.engine = engine
        self._confirm_lock = Lock()
        self._conversation_lock = Lock()
        self.model_name = settings.llm_model
        self.remote_trace = LangSmithTrace(settings)
        settings.agent_checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(settings.agent_checkpoint_path, timeout=10, check_same_thread=False)
        self._owned_llm = None
        try:
            saver = SqliteSaver(self.connection)
            saver.setup()
            self.saver = saver
            self._cleanup_checkpoints()
            self._restore_activity_times()
            if llm is None:
                self._owned_llm = llm = ChatCompletionsLLM(settings)
            graph = build_workflow(
                engine, llm,
                retriever if retriever is not None else ChromaKnowledge(settings, engine),
                provider=settings.llm_provider, model_name=settings.llm_model,
            )
            self.graph = graph.compile(checkpointer=saver)
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        try:
            if self._owned_llm is not None:
                self._owned_llm.close()
        finally:
            try:
                self.connection.close()
            finally:
                self.remote_trace.close()

    @staticmethod
    def _config(thread_id: str) -> dict:
        return {
            "configurable": {"thread_id": thread_id, "trace_id": current_trace_id()}, "recursion_limit": 16,
        }

    def _run_graph(self, action, config: dict, operation: str) -> tuple[ChatResponse, StateSnapshot]:
        trace_id = config["configurable"]["trace_id"]
        thread_id = config["configurable"]["thread_id"]
        with trace_scope(trace_id=trace_id, thread_id=thread_id):
            span = None
            try:
                with observe("agent.run", model_name=self.model_name, operation=operation) as span:
                    # Export only the allowlisted span. Graph state can contain private financial data.
                    with tracing_context(enabled=False, parent=False):
                        self.graph.invoke(action, config, durability="sync")
                        snapshot = self.graph.get_state(config)
                    response = self._response(thread_id, snapshot)
                    span.status, span.error_code = response.status, response.error_code
                    span.intent = snapshot.values.get("intent")
                    return response, snapshot
            finally:
                if span is not None:
                    self.remote_trace.record(span)

    @staticmethod
    def _owned_thread(session: Session, user_id: int, thread_id: str) -> ChatThread:
        thread = session.get(ChatThread, thread_id)
        if thread is None or thread.user_id != user_id:
            raise ThreadNotFound
        return thread

    @staticmethod
    def _pending(snapshot: StateSnapshot) -> bool:
        return any(task.name == "human_confirmation" and task.interrupts for task in snapshot.tasks)

    def _response(self, thread_id: str, snapshot: StateSnapshot) -> ChatResponse:
        if self._pending(snapshot):
            return ChatResponse(
                status="PENDING_CONFIRMATION", thread_id=thread_id,
                message="Hãy kiểm tra bản nháp rồi xác nhận hoặc hủy thao tác.",
                pending_action=PENDING_ADAPTER.validate_python(snapshot.values["pending_action"]),
            )
        if snapshot.values.get("final_response"):
            return ChatResponse.model_validate(snapshot.values["final_response"])
        return ChatResponse(
            status="ERROR", thread_id=thread_id, error_code="CHAT_INTERRUPTED",
            message="Tác vụ chưa hoàn tất. Hãy thử lại.",
        )

    @staticmethod
    def _conversation(session: Session, user_id: int, public_id: UUID | None) -> ChatConversation | None:
        query = select(ChatConversation).where(ChatConversation.user_id == user_id)
        if public_id is not None:
            result = session.scalar(query.where(ChatConversation.public_id == str(public_id)))
            if result is None:
                raise ConversationNotFound
            return result
        return session.scalar(query.order_by(ChatConversation.id.desc()).limit(1))

    @staticmethod
    def _new_conversation(session: Session, user_id: int) -> ChatConversation:
        conversation = ChatConversation(public_id=str(uuid4()), user_id=user_id)
        session.add(conversation)
        session.flush()
        return conversation

    @staticmethod
    def _turns(session: Session, conversation_id: int, limit: int, before: int | None = None) -> list[TurnRecord]:
        query = (
            select(ChatTurn, ChatThread).join(ChatThread, ChatThread.id == ChatTurn.thread_id)
            .where(ChatTurn.conversation_id == conversation_id, ChatTurn.response.is_not(None))
        )
        if before is not None:
            query = query.where(ChatTurn.id < before)
        recent = session.execute(query.order_by(ChatTurn.id.desc()).limit(limit)).all()
        return list(reversed(recent))

    @staticmethod
    def _latest_transaction(session: Session, conversation_id: int) -> TurnRecord | None:
        # Include closed versions. Otherwise closing one draft could reactivate an older legacy draft.
        return session.execute(
            select(ChatTurn, ChatThread).join(ChatThread, ChatThread.id == ChatTurn.thread_id)
            .where(ChatTurn.conversation_id == conversation_id, ChatTurn.intent == "CREATE_TRANSACTION", or_(
                ChatTurn.response["pending_state"].as_string().is_not(None),
                ChatTurn.response["status"].as_string() == "PENDING_CONFIRMATION",
            ))
            .order_by(ChatTurn.id.desc()).limit(1)
        ).first()

    @staticmethod
    def _phase(turn: ChatTurn) -> str | None:
        response = turn.response or {}
        return response.get("pending_state") or (
            "ready_for_confirmation" if response.get("status") == "PENDING_CONFIRMATION" else None
        )

    def _revision(self, latest: TurnRecord | None) -> tuple | None:
        if latest is None:
            return None
        turn, thread = latest
        return turn.thread_id, self._phase(turn), thread.decision

    def _active_response(self, latest: TurnRecord | None) -> ChatResponse | None:
        if latest is None:
            return None
        turn, thread = latest
        phase = self._phase(turn)
        if phase not in ACTIVE_PHASES or thread.decision is not None or thread.receipt is not None:
            return None
        return ChatResponse.model_validate(turn.response).model_copy(update={"pending_state": phase})

    def _dialogue_context(self, active: ChatResponse | None) -> dict:
        if active is None:
            return {}
        snapshot = self.graph.get_state(self._config(str(active.thread_id)))
        values = snapshot.values.get("transaction_work")
        if values is None:
            # Drafts created before dialogue tracking already have validated slots in the response.
            assert isinstance(active.pending_action, PendingTransaction)
            values = TransactionWork.from_draft(active.pending_action).model_dump(mode="json")
        return {"work": values, "phase": active.pending_state, "awaiting": active.error_code}

    @staticmethod
    def _closed_response(response: ChatResponse, phase: str) -> ChatResponse:
        return response.model_copy(update={
            "status": "COMPLETED", "pending_state": phase, "pending_action": None, "error_code": None,
            "message": "Bản nháp này đã được thay thế." if phase == "superseded" else "Đã hủy giao dịch đang chờ.",
        })

    def _visible_response(
        self, turn: ChatTurn, thread: ChatThread, latest: TurnRecord | None, conversation_id: UUID,
    ) -> ChatResponse:
        response = ChatResponse.model_validate(thread.receipt or turn.response)
        if turn.intent == "CREATE_TRANSACTION" and self._phase(turn):
            version = turn.response.get("draft_version") or 1
            if thread.receipt is not None:
                phase = "cancelled" if thread.decision == "CANCEL" else "confirmed"
            else:
                phase = self._phase(turn)
                if phase in ACTIVE_PHASES and latest is not None and latest[0].id != turn.id:
                    response = self._closed_response(response, "superseded")
                    phase = "superseded"
            response = response.model_copy(update={"pending_state": phase, "draft_version": version})
        return response.model_copy(update={"conversation_id": conversation_id})

    def new_conversation(self, user_id: int) -> ConversationHistory:
        with self._conversation_lock, Session(self.engine) as session, session.begin():
            conversation = self._new_conversation(session, user_id)
            return ConversationHistory(conversation_id=conversation.public_id)

    def list_conversations(self, user_id: int) -> list[ConversationItem]:
        first_message = (select(func.substr(ChatTurn.message, 1, 72))
                         .where(ChatTurn.conversation_id == ChatConversation.id)
                         .order_by(ChatTurn.id).limit(1).scalar_subquery())
        with Session(self.engine) as session:
            rows = session.execute(select(ChatConversation, first_message)
                                   .where(ChatConversation.user_id == user_id)
                                   .order_by(ChatConversation.updated_at.desc(), ChatConversation.id.desc()))
            return [ConversationItem(conversation_id=c.public_id, updated_at=c.updated_at,
                                     title=" ".join((title or "").split()) or "Cuộc trò chuyện mới")
                    for c, title in rows]

    def history_page(self, user_id: int, public_id: UUID, before: int | None, limit: int) -> ConversationPage:
        with Session(self.engine) as session:
            conversation = self._conversation(session, user_id, public_id)
            latest = self._latest_transaction(session, conversation.id)
            rows = self._turns(session, conversation.id, limit + 1, before)
            page = rows[-limit:]
            pinned = None
            if before is None and page and latest and latest[0].id < page[0][0].id:
                active = self._active_response(latest)
                if active:
                    pinned = ConversationTurn(message=latest[0].message, response=active)
            return ConversationPage(conversation_id=public_id, next_before=page[0][0].id if len(rows)>limit else None,
                                    earlier_pending=pinned,
                                    turns=[ConversationTurn(message=t.message, response=self._visible_response(
                                        t, thread, latest, public_id)) for t, thread in page])

    def _cleanup_checkpoints(self) -> None:
        with Session(self.engine) as session, session.begin():
            for item in session.scalars(select(DeletedChatCheckpoint)).all():
                try:
                    self.saver.delete_thread(item.thread_id)
                except sqlite3.OperationalError:
                    with observe("chat.checkpoint_cleanup") as span:
                        span.status, span.error_code = "DEFERRED", "CHECKPOINT_CLEANUP_PENDING"
                else:
                    session.delete(item)

    def _restore_activity_times(self) -> None:
        # The previous schema had no timestamp. LangGraph stores a timestamp on each checkpoint.
        with Session(self.engine) as session:
            rows = session.execute(select(ChatTurn.conversation_id, ChatTurn.thread_id).join(ChatConversation)
                                   .where(ChatConversation.updated_at.is_(None))).all()
        newest = {}
        for cid, thread_id in rows:
            record = self.connection.execute("SELECT max(checkpoint_id) FROM checkpoints "
                                             "WHERE thread_id=? AND checkpoint_ns=''", (thread_id,)).fetchone()
            if record[0] and (cid not in newest or record[0] > newest[cid][0]):
                newest[cid] = (record[0], thread_id)
        with Session(self.engine) as session, session.begin():
            for cid, (checkpoint, tid) in newest.items():
                saved = self.saver.get_tuple({"configurable": {"thread_id": tid, "checkpoint_id": checkpoint}})
                if saved and saved.checkpoint.get("ts"):
                    stamp = datetime.fromisoformat(saved.checkpoint["ts"]).astimezone(UTC).replace(tzinfo=None)
                    session.execute(update(ChatConversation).where(ChatConversation.id == cid,
                                    ChatConversation.updated_at.is_(None)).values(updated_at=stamp))

    def delete_conversation(self, user_id: int, public_id: UUID) -> None:
        with self._confirm_lock, self._conversation_lock:
            with Session(self.engine) as session, session.begin():
                session.execute(text("BEGIN IMMEDIATE"))
                conversation = self._conversation(session, user_id, public_id)
                threads = session.scalars(select(ChatTurn.thread_id).where(ChatTurn.conversation_id == conversation.id)).all()
                session.add_all(DeletedChatCheckpoint(thread_id=tid) for tid in threads)
                session.execute(delete(ChatTurn).where(ChatTurn.conversation_id == conversation.id))
                for start in range(0, len(threads), 500):
                    session.execute(delete(ChatThread).where(ChatThread.user_id == user_id,
                                                            ChatThread.id.in_(threads[start:start+500])))
                session.delete(conversation)
            self._cleanup_checkpoints()

    def history(self, user_id: int, conversation_id: UUID | None = None) -> ConversationHistory:
        with Session(self.engine) as session:
            conversation = self._conversation(session, user_id, conversation_id)
            if conversation is None:
                return ConversationHistory()
            public_id = UUID(conversation.public_id)
            latest = self._latest_transaction(session, conversation.id)
            recent = self._turns(session, conversation.id, HISTORY_TURNS)
            if self._active_response(latest) and (not recent or latest[0].id < recent[0][0].id):
                recent = [latest, *recent[1:]]
            turns = [
                ConversationTurn(message=turn.message, response=self._visible_response(turn, thread, latest, public_id))
                for turn, thread in recent
            ]
            return ConversationHistory(conversation_id=public_id, turns=turns)

    @staticmethod
    def _context(turn: ChatTurn, thread: ChatThread) -> dict:
        response = thread.receipt or turn.response
        share_user = turn.intent not in {
            None, "CREATE_TRANSACTION", "SET_BUDGET", "PENDING_ACTION_REQUEST",
        } and response["status"] != "ERROR"
        context = {
            "user": turn.message[:1500] if share_user else "",
            "intent": turn.intent,
            "status": response["status"], "error_code": response.get("error_code"),
        }
        if turn.intent in {"GENERAL_CONVERSATION", "GREETING", "DATE_TIME"} and response["status"] == "COMPLETED":
            context["assistant"] = response["message"][:500]
        if turn.intent == "PERSONAL_FINANCIAL_ADVICE" and response.get("advisory_scope"):
            context["advisory_scope"] = response["advisory_scope"]
        return context

    def start(self, user_id: int, message: str, conversation_id: UUID | None = None) -> ChatResponse:
        thread_id = str(uuid4())
        clean_message = sanitize(message)
        with self._conversation_lock, Session(self.engine) as session, session.begin():
            session.execute(text("BEGIN IMMEDIATE"))
            conversation = self._conversation(session, user_id, conversation_id)
            if conversation is None:
                conversation = self._new_conversation(session, user_id)
            public_id = UUID(conversation.public_id)
            latest = self._latest_transaction(session, conversation.id)
            revision, active = self._revision(latest), self._active_response(latest)
            history = [self._context(turn, thread)
                       for turn, thread in self._turns(session, conversation.id, CONTEXT_TURNS)]
            session.add(ChatThread(id=thread_id, user_id=user_id))
            session.flush()
            turn = ChatTurn(conversation_id=conversation.id, thread_id=thread_id, message=clean_message)
            session.add(turn)
            session.flush()
            turn_id = turn.id
        now = local_now()
        config = self._config(thread_id)
        response, snapshot = self._run_graph({
            "thread_id": thread_id, "user_id": user_id, "input": clean_message,
            "current_date": now.date().isoformat(), "current_datetime": now.isoformat(),
            "history": history, "active_transaction": self._dialogue_context(active),
        }, config, "start")
        response = response.model_copy(update={"conversation_id": public_id})
        return self._publish_turn(turn_id, revision, response, snapshot)

    def _publish_turn(
        self, turn_id: int, revision: tuple | None, response: ChatResponse, snapshot: StateSnapshot,
    ) -> ChatResponse:
        action = snapshot.values.get("dialogue_action") or (
            "unclassified" if snapshot.values.get("active_transaction") else "new_request"
        )
        intent = snapshot.values.get("intent")
        has_work = snapshot.values.get("transaction_work") is not None
        cancel = action == "cancel_pending" and response.status == "COMPLETED"
        transition = None
        pending_id = None
        with Session(self.engine) as session, session.begin():
            session.execute(text("BEGIN IMMEDIATE"))
            turn = session.get(ChatTurn, turn_id)
            if turn is None or turn.thread_id != str(response.thread_id):
                # Deletion may overlap an in-flight model request or a reused SQLite rowid.
                self.saver.delete_thread(str(response.thread_id))
                raise ConversationNotFound
            session.get(ChatConversation, turn.conversation_id).updated_at = utc_now()
            if has_work or cancel:
                latest = self._latest_transaction(session, turn.conversation_id)
                active = self._active_response(latest)
                confirming = latest is not None and self._phase(latest[0]) in ACTIVE_PHASES and (
                    latest[1].decision is not None and latest[1].receipt is None
                )
                if self._revision(latest) != revision or confirming or (cancel and active is None):
                    response = response.model_copy(update={
                        "status": "NEEDS_CLARIFICATION", "pending_action": None, "error_code": "PENDING_ACTION_CHANGED",
                        "message": "Khoản đang xử lý vừa thay đổi. Hãy xem trạng thái mới rồi gửi lại yêu cầu.",
                    })
                else:
                    previous = active.pending_state if active else "none"
                    if active is not None:
                        closed = self._closed_response(active, "cancelled" if cancel else "superseded")
                        latest[0].response = closed.model_dump(mode="json")
                    if cancel:
                        pending_id = active.thread_id
                        transition = f"{previous}->cancelled"
                        response = response.model_copy(update={
                            "pending_state": "cancelled", "draft_version": active.draft_version or 1,
                        })
                    else:
                        phase = "ready_for_confirmation" if response.status == "PENDING_CONFIRMATION" else "collecting"
                        version = ((latest[0].response.get("draft_version") or 1) + 1) if latest else 1
                        response = response.model_copy(update={"pending_state": phase, "draft_version": version})
                        pending_id = response.thread_id
                        transition = f"{previous}->superseded->{phase}" if active else f"{previous}->{phase}"
            turn.response = response.model_dump(mode="json")
            turn.intent = intent
        if snapshot.values.get("active_transaction") or has_work:
            self._observe_dialogue(response, action, pending_id or (revision[0] if revision else None), transition)
        return response

    @staticmethod
    def _observe_dialogue(response: ChatResponse, action: str, pending_id, transition: str | None) -> None:
        with trace_scope(trace_id=current_trace_id(), thread_id=str(response.thread_id)), observe(
            "chat.dialogue",
            dialogue={
                "conversation_id": str(response.conversation_id) if response.conversation_id else None,
                "pending_action_id": str(pending_id) if pending_id else None,
                "action_type": action, "pending_state_transition": transition,
                "draft_version": response.draft_version, "validation_result": response.error_code or "OK",
                "confirmation_status": response.pending_state,
            },
        ) as span:
            span.status, span.error_code = response.status, response.error_code

    @staticmethod
    def _thread_turn(session: Session, thread_id: str) -> ChatTurn | None:
        return session.scalar(select(ChatTurn).where(ChatTurn.thread_id == thread_id))

    def state(self, user_id: int, thread_uuid: UUID) -> ChatResponse:
        thread_id = str(thread_uuid)
        with Session(self.engine) as session:
            thread = self._owned_thread(session, user_id, thread_id)
            turn = self._thread_turn(session, thread_id)
            if turn is not None:
                conversation = session.get(ChatConversation, turn.conversation_id)
                if conversation is None:
                    raise ThreadNotFound
                if turn.response is not None:
                    latest = self._latest_transaction(session, turn.conversation_id)
                    visible = self._visible_response(turn, thread, latest, UUID(conversation.public_id))
                    if thread.decision is not None and thread.receipt is None:
                        graph_response = self._response(thread_id, self.graph.get_state(self._config(thread_id)))
                        if graph_response.status == "ERROR":
                            return graph_response.model_copy(update={
                                "conversation_id": visible.conversation_id,
                                "draft_version": visible.draft_version,
                                "pending_state": "cancelled" if visible.draft_version is not None else None,
                            })
                    return visible
            if thread.receipt is not None:
                return ChatResponse.model_validate(thread.receipt)
        return self._response(thread_id, self.graph.get_state(self._config(thread_id)))

    def confirm(self, user_id: int, thread_uuid: UUID, decision: Decision) -> ChatResponse:
        thread_id = str(thread_uuid)
        config = self._config(thread_id)

        with self._confirm_lock:
            with Session(self.engine) as session, session.begin():
                session.execute(text("BEGIN IMMEDIATE"))
                thread = self._owned_thread(session, user_id, thread_id)
                if thread.decision and thread.decision != decision:
                    raise ThreadConflict("Phiên này đã ghi nhận một quyết định khác.")
                already_completed = thread.receipt is not None
                if not already_completed:
                    snapshot = self.graph.get_state(config)
                    if thread.decision is None:
                        turn = self._thread_turn(session, thread_id)
                        if turn is not None:
                            if turn.response is None:
                                raise ThreadConflict("Phiên này chưa có bản nháp được công bố.")
                            if turn.intent == "CREATE_TRANSACTION":
                                current = self._active_response(self._latest_transaction(session, turn.conversation_id))
                                if current is None or str(current.thread_id) != thread_id:
                                    raise ThreadConflict("Bản nháp này không còn hiệu lực. Hãy xem bản nháp mới nhất.")
                        if not self._pending(snapshot):
                            raise ThreadConflict("Phiên này không có thao tác đang chờ xác nhận.")
                        thread.decision = decision

            if already_completed:
                return self.state(user_id, thread_uuid)
            if self._pending(snapshot):
                self._run_graph(Command(resume=decision), config, "confirm")
            elif snapshot.next:
                self._run_graph(None, config, "resume")
            result = self.state(user_id, thread_uuid)
            if result.status == "ERROR" and result.pending_state == "cancelled":
                with Session(self.engine) as session, session.begin():
                    turn = self._thread_turn(session, thread_id)
                    turn.response = result.model_dump(mode="json")
            if result.pending_state in {"cancelled", "confirmed"}:
                self._observe_dialogue(result, decision.lower(), thread_id, f"ready_for_confirmation->{result.pending_state}")
            return result
