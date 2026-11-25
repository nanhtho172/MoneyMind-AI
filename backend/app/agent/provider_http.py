import socket
import ssl
import time
from contextlib import ExitStack
from dataclasses import dataclass

import httpx

from backend.app.core.config import Settings

_SOURCE_ADDRESS = {"IPv6": "::", "IPv4": "0.0.0.0"}
_FAMILIES = {"auto": ("IPv6", "IPv4"), "ipv6": ("IPv6",), "ipv4": ("IPv4",)}
_TIMEOUT = httpx.Timeout(15, connect=5)


@dataclass(frozen=True)
class Failure:
    code: str
    reason: str


class ProviderNetworkError(Exception):
    def __init__(self, attempts: list[tuple[str, Failure]]):
        self.code = attempts[-1][1].code
        if any(failure.code == "LLM_NETWORK_DENIED" for _, failure in attempts):
            self.code = "LLM_NETWORK_DENIED"
        paths = ", ".join(f"{path}: {failure.reason}" for path, failure in attempts)
        super().__init__(f"Lỗi đường kết nối đến nhà cung cấp AI ({paths}).")


def _failure(error: httpx.RequestError) -> Failure:
    cause: BaseException | None = error
    while cause is not None:
        if isinstance(cause, ssl.SSLCertVerificationError):
            return Failure("LLM_TLS_ERROR", "lỗi xác minh chứng chỉ TLS")
        if isinstance(cause, socket.gaierror):
            return Failure("LLM_DNS_ERROR", "lỗi DNS hoặc địa chỉ không tương thích")
        cause = cause.__cause__
    if isinstance(error, httpx.TimeoutException):
        return Failure("LLM_TIMEOUT", "hết thời gian chờ")
    return Failure("LLM_UNAVAILABLE", "kết nối thất bại")


def _network_denied(response: httpx.Response) -> bool:
    if response.status_code != 403:
        return False
    try:
        message = response.json()["error"]["message"]
    except (ValueError, KeyError, TypeError):
        return False
    return (
        isinstance(message, str)
        and message.strip().rstrip(".").casefold() == "access denied. please check your network settings"
    )


class ProviderHttp:
    """Own one pool per configured route and remember the last successful Groq family."""

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self._groq = settings.llm_provider == "groq"
        self._stack = ExitStack()
        try:
            if self._groq and transport is None:
                self._clients = {
                    family: self._stack.enter_context(httpx.Client(
                        timeout=_TIMEOUT,
                        transport=httpx.HTTPTransport(local_address=_SOURCE_ADDRESS[family], retries=0),
                    ))
                    for family in _FAMILIES[settings.groq_ip_family]
                }
            else:
                self._clients = {
                    "mặc định": self._stack.enter_context(httpx.Client(timeout=_TIMEOUT, transport=transport)),
                }
        except BaseException:
            self.close()
            raise
        self._preferred = next(iter(self._clients))

    def close(self) -> None:
        self._stack.close()

    def post(self, endpoint: str, headers: dict[str, str], payload: dict, *, retry: bool) -> httpx.Response:
        path = self._preferred
        alternate = next((name for name in self._clients if name != path), None)
        failures: list[tuple[str, Failure]] = []
        for attempt in range(2):
            try:
                response = self._clients[path].post(endpoint, headers=headers, json=payload)
            except httpx.RequestError as error:
                failure = _failure(error)
                failures.append((path, failure))
                connect_failed = isinstance(error, (httpx.ConnectError, httpx.ConnectTimeout))
                if attempt == 0 and connect_failed and failure.code != "LLM_TLS_ERROR":
                    if alternate is not None:
                        path = alternate
                        continue
                    if retry:
                        time.sleep(0.25)
                        continue
                raise ProviderNetworkError(failures) from None

            if self._groq and _network_denied(response):
                failures.append((path, Failure("LLM_NETWORK_DENIED", "HTTP 403 do đường mạng bị từ chối")))
                if attempt == 0 and retry and alternate is not None:
                    path = alternate
                    continue
                raise ProviderNetworkError(failures)

            if response.status_code == 429 or response.status_code >= 500:
                if attempt == 0 and retry:
                    time.sleep(0.5)
                    continue
            if response.is_success:
                self._preferred = path
            return response
        raise AssertionError("provider request loop exhausted")
