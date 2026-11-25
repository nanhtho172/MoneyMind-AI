import json
import logging
import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from uuid import uuid4

from langsmith import Client

from backend.app.core.config import Settings

LOGGER = logging.getLogger("moneymind.telemetry")
LOGGER.setLevel(logging.INFO)
if not LOGGER.handlers:
    LOGGER.addHandler(logging.StreamHandler())
LOGGER.propagate = False

_scope: ContextVar[dict] = ContextVar("moneymind_trace", default={})
_ERROR_CODE = re.compile(r"[A-Z][A-Z0-9_]{2,55}")
_TOKEN_FIELDS = ("prompt_tokens", "completion_tokens", "total_tokens")
_PROVIDER_CODES = frozenset({
    "tool_use_failed", "json_validate_failed", "invalid_request_error", "invalid_function_parameters",
    "invalid_api_key", "insufficient_quota", "rate_limit_exceeded", "model_not_found",
    "context_length_exceeded", "model_decommissioned", "invalid_value", "failed_generation",
})
_DIALOGUE_FIELDS = (
    "conversation_id", "pending_action_id", "action_type", "pending_state_transition",
    "draft_version", "validation_result", "confirmation_status",
)
_MODEL_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,127}")


def safe_model_id(value: object) -> str | None:
    if isinstance(value, str) and _MODEL_ID.fullmatch(value) and not value.lower().startswith(
        ("gsk_", "sk-", "sk_", "ghp_")
    ):
        return value
    return None


def current_trace_id() -> str:
    return _scope.get().get("trace_id") or uuid4().hex


@contextmanager
def trace_scope(
    *, trace_id: str, thread_id: str | None = None, intent: str | None = None, agent_node: str | None = None,
):
    token = _scope.set({
        "trace_id": trace_id, "thread_id": thread_id, "intent": intent, "agent_node": agent_node,
    })
    try:
        yield
    finally:
        _scope.reset(token)


@dataclass
class Span:
    status: str = "OK"
    error_code: str | None = None
    intent: str | None = None
    token_usage: dict | None = None
    response_model: str | None = None
    http_status: int | None = None
    provider_error_code: str | None = None
    fields: dict | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    rag_hits: list[tuple[str, str, float]] | None = None


@contextmanager
def observe(
    event: str, *, model_name: str | None = None, tool_name: str | None = None, operation: str | None = None,
    provider: str | None = None, document_id: str | None = None,
    dialogue: dict | None = None,
):
    span = Span(started_at=datetime.now(UTC))
    started = perf_counter()
    context = _scope.get()
    try:
        yield span
    except Exception as error:
        if span.status == "OK":
            span.status = "ERROR"
            span.error_code = getattr(error, "code", None) or "UNEXPECTED_ERROR"
        raise
    finally:
        span.ended_at = datetime.now(UTC)
        code = span.error_code
        usage = span.token_usage or {}
        fields = {
            "timestamp": span.ended_at.isoformat(),
            "event": event,
            "trace_id": context.get("trace_id") or uuid4().hex,
            "thread_id": context.get("thread_id"),
            "intent": span.intent or context.get("intent"),
            "agent_node": context.get("agent_node"),
            "tool_name": tool_name,
            "status": span.status,
            "latency_ms": round((perf_counter() - started) * 1000, 2),
            "error_code": code if isinstance(code, str) and _ERROR_CODE.fullmatch(code) else None,
            "model_name": model_name,
            "operation": operation,
        }
        usage = {
            key: usage[key] for key in _TOKEN_FIELDS
            if type(usage.get(key)) is int and usage[key] >= 0
        }
        if usage:
            fields["token_usage"] = usage
        if provider is not None:
            fields["provider"] = provider
        if event == "llm.request":
            fields["requested_model"] = safe_model_id(model_name)
            if span.http_status is not None:
                fields["http_status"] = span.http_status
            if span.provider_error_code in _PROVIDER_CODES:
                fields["provider_error_code"] = span.provider_error_code
            if span.response_model:
                fields["response_model"] = safe_model_id(span.response_model)
        if document_id is not None:
            fields["document_id"] = document_id
        if dialogue is not None:
            fields.update({key: dialogue.get(key) for key in _DIALOGUE_FIELDS})
        if span.rag_hits is not None:
            fields["document_ids"] = sorted({item[0] for item in span.rag_hits})
            fields["retrieved_chunk_ids"] = [item[1] for item in span.rag_hits]
            fields["similarity_scores"] = [round(item[2], 4) for item in span.rag_hits]
        span.fields = fields
        LOGGER.info(json.dumps(fields, ensure_ascii=True, separators=(",", ":")))


class LangSmithTrace:
    def __init__(self, settings: Settings):
        secret = settings.langsmith_api_key
        key = secret.get_secret_value().strip() if secret else ""
        self.project = settings.langsmith_project
        self.client = None
        if key and settings.langsmith_tracing:
            with observe("langsmith.setup") as span:
                try:
                    self.client = Client(
                        api_key=key, hide_inputs=True, hide_outputs=True,
                        omit_traced_runtime_info=True, otel_enabled=False,
                    )
                except Exception:
                    span.status, span.error_code = "ERROR", "LANGSMITH_SETUP_FAILED"

    def record(self, span: Span) -> None:
        if self.client is None or span.fields is None:
            return
        try:
            self.client.create_run(
                name="moneymind.chat", inputs={}, outputs={}, run_type="chain", project_name=self.project,
                start_time=span.started_at, end_time=span.ended_at, extra={"metadata": span.fields},
            )
        except Exception:
            with observe("langsmith.export") as failure:
                failure.status, failure.error_code = "ERROR", "LANGSMITH_EXPORT_FAILED"

    def close(self) -> None:
        if self.client is not None:
            try:
                self.client.flush(timeout=3)
            except Exception:
                with observe("langsmith.flush") as failure:
                    failure.status, failure.error_code = "ERROR", "LANGSMITH_FLUSH_FAILED"
