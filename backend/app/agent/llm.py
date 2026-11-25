import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from backend.app.agent.provider_http import ProviderHttp, ProviderNetworkError
from backend.app.core.config import Settings
from backend.app.core.observability import LOGGER, Span, observe, safe_model_id

Output = TypeVar("Output", bound=BaseModel)
Result = TypeVar("Result")


class AgentProblem(Exception):
    def __init__(self, code: str, message: str, *, clarification: bool = False):
        super().__init__(message)
        self.code = code
        self.clarification = clarification


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict


class LLM(Protocol):
    def structured(self, schema: type[Output], instruction: str, data: dict) -> Output: ...

    def select_tool(self, instruction: str, data: dict, tools: list[dict]) -> ToolCall: ...


class ChatCompletionsLLM:
    def __init__(self, settings: Settings, *, transport: httpx.BaseTransport | None = None, retry: bool = True):
        self.settings = settings
        self.retry = retry
        self._http = ProviderHttp(settings, transport)

    def close(self) -> None:
        self._http.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _message(self, instruction: str, data: dict, parse: Callable[[dict], Result], **options) -> Result:
        diagnostics = {}
        try:
            with observe("llm.request", model_name=safe_model_id(self.settings.llm_model),
                         provider=self.settings.llm_provider,
                         operation="function_call" if "tools" in options else "structured_output") as span:
                return parse(self._request(instruction, data, span, diagnostics, **options))
        except AgentProblem:
            spec = options.get("response_format", {}).get("json_schema")
            if self.settings.llm_provider == "groq" and spec and span.fields:
                # Reuse the completed span's filtered fields, trace ID and latency.
                canonical = json.dumps(spec["schema"], sort_keys=True, separators=(",", ":"))
                LOGGER.info(json.dumps({
                    **span.fields, "event": "llm.structured_error", **diagnostics,
                    "schema_name": spec["name"], "schema_version": sha256(canonical.encode()).hexdigest(),
                    "strict": spec["strict"],
                }, separators=(",", ":")))
            raise

    def _request(self, instruction: str, data: dict, span: Span, diagnostics: dict, **options) -> dict:
        secret = self.settings.llm_api_key
        if secret is None or not secret.get_secret_value().strip():
            raise AgentProblem("LLM_NOT_CONFIGURED", "Chưa cấu hình khóa cho nhà cung cấp AI.")
        endpoint = f"{str(self.settings.llm_base_url).rstrip('/')}/chat/completions"
        payload = {
            "model": self.settings.llm_model,
            "messages": [
                {"role": "system", "content": instruction},
                {"role": "user", "content": json.dumps(data, ensure_ascii=False)},
            ],
            "max_completion_tokens": 2048,
            **options,
        }
        if self.settings.llm_provider == "groq" and self.settings.llm_model.startswith("openai/gpt-oss-"):
            payload["reasoning_effort"] = self.settings.llm_reasoning_effort
            diagnostics["reasoning_effort"] = payload["reasoning_effort"]

        try:
            response = self._http.post(
                endpoint, {"Authorization": f"Bearer {secret.get_secret_value().strip()}"}, payload, retry=self.retry,
            )
        except ProviderNetworkError as error:
            if error.code == "LLM_NETWORK_DENIED":
                span.http_status = 403
            raise AgentProblem(error.code, str(error)) from None
        span.http_status = response.status_code
        if not response.is_success:
            request_id = response.headers.get("x-request-id")
            if request_id and re.fullmatch(r"(?:req[_-][A-Za-z0-9_-]{1,100}|[A-Fa-f0-9-]{16,64})", request_id):
                diagnostics["provider_request_id"] = request_id
            try:
                detail = response.json()["error"]
                code = detail.get("code") or detail.get("type")
                span.provider_error_code = code if isinstance(code, str) else None
            except (ValueError, KeyError, TypeError, AttributeError):
                pass
        if response.status_code == 401:
            raise AgentProblem("LLM_AUTH_ERROR", "Khóa API bị nhà cung cấp từ chối (HTTP 401).")
        if response.status_code == 403:
            raise AgentProblem("LLM_FORBIDDEN", "Nhà cung cấp AI từ chối quyền truy cập (HTTP 403).")
        if response.status_code == 429:
            raise AgentProblem("LLM_RATE_LIMIT", "AI đang bị giới hạn lượt gọi. Hãy thử lại sau.")
        if response.status_code >= 500:
            raise AgentProblem("LLM_UNAVAILABLE", "Nhà cung cấp AI đang tạm gián đoạn.")
        if not response.is_success:
            raise AgentProblem("LLM_REQUEST_REJECTED", f"AI chưa xử lý được yêu cầu (HTTP {response.status_code}). "
                               "Bạn có thể thử lại hoặc dùng mã tra cứu để kiểm tra lỗi.")
        try:
            result = response.json()
            usage = result.get("usage") if isinstance(result, dict) else None
            if isinstance(usage, dict):
                span.token_usage = usage
            if isinstance(result, dict):
                span.response_model = safe_model_id(result.get("model"))
            message = result["choices"][0]["message"]
            if not isinstance(message, dict):
                raise TypeError
        except (ValueError, KeyError, IndexError, TypeError):
            raise AgentProblem("INVALID_MODEL_OUTPUT", "AI trả về dữ liệu không hợp lệ.") from None
        return message

    def structured(self, schema: type[Output], instruction: str, data: dict) -> Output:
        def parse(message: dict) -> Output:
            try:
                return schema.model_validate_json(message.get("content"))
            except ValidationError:
                raise AgentProblem("INVALID_MODEL_OUTPUT", "AI trả về JSON không phù hợp với yêu cầu.") from None

        return self._message(
            instruction, data, parse,
            response_format={
                "type": "json_schema",
                "json_schema": {"name": schema.__name__, "strict": True, "schema": schema.model_json_schema()},
            },
        )

    def select_tool(self, instruction: str, data: dict, tools: list[dict]) -> ToolCall:
        def parse(message: dict) -> ToolCall:
            try:
                calls = message["tool_calls"]
                if not isinstance(calls, list) or len(calls) != 1 or calls[0]["type"] != "function":
                    raise ValueError
                function = calls[0]["function"]
                arguments = json.loads(function["arguments"])
                if not isinstance(arguments, dict) or not isinstance(function["name"], str):
                    raise ValueError
                return ToolCall(function["name"], arguments)
            except (ValueError, TypeError, IndexError, KeyError):
                raise AgentProblem("INVALID_TOOL_CALL", "AI cần chọn đúng một công cụ đọc.") from None

        return self._message(instruction, data, parse, tools=tools, tool_choice="required")
