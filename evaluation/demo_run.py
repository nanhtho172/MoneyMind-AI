"""Replay the demo plan through FastAPI on fresh SQLite copies and an isolated, real Chroma index."""

import argparse
import json
import logging
import os
import re
import sqlite3
import tempfile
from collections import Counter
from contextlib import ExitStack, closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from backend.app.agent.guardrails import folded
from backend.app.agent.llm import AgentProblem, ChatCompletionsLLM
from backend.app.core.calendar import LOCAL_TIME_ZONE, local_now
from backend.app.core.observability import LOGGER
from backend.app.main import create_app
from evaluation.demo_fixture import DOCUMENTS, isolated_settings, login, seed, upload
from evaluation.demo_provider import DELETED, INJECTION, Script

HERE = Path(__file__).resolve().parent
NOW = datetime(2026, 11, 24, 9, 15, tzinfo=LOCAL_TIME_ZONE)
CATALOG = json.loads((HERE / "demo_cases.json").read_text(encoding="utf-8"))
INFRA = {
    "LLM_NOT_CONFIGURED",
    "LLM_AUTH_ERROR",
    "LLM_FORBIDDEN",
    "LLM_RATE_LIMIT",
    "LLM_UNAVAILABLE",
    "LLM_NETWORK_ERROR",
    "LLM_DNS_ERROR",
    "LLM_TLS_ERROR",
    "LLM_TIMEOUT",
    "LLM_CONNECTION_ERROR",
    "LLM_NETWORK_BLOCKED",
    "LIVE_CALL_LIMIT",
}


class Blocked(Exception):
    pass


def check(condition, message):
    if not condition:
        raise AssertionError(message)


class Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.events = []

    def emit(self, record):
        self.events.append(json.loads(record.getMessage()))


class LimitedGroq(ChatCompletionsLLM):
    def __init__(self, settings, limit):
        super().__init__(settings, retry=False)
        self.calls, self.limit = 0, limit
        self.responses = []
        for client in self._http._clients.values():
            client.event_hooks["response"].append(self.record_http)

    def record_http(self, response):
        response.read()
        entry = {"http_status": response.status_code}
        if not response.is_success:
            try:
                error = response.json()["error"]
                for key in ("type", "code"):
                    value = error.get(key)
                    if value in {
                        "tool_use_failed",
                        "invalid_request_error",
                        "invalid_api_key",
                        "rate_limit_exceeded",
                        "json_validate_failed",
                        "invalid_function_parameters",
                        "model_not_found",
                        "failed_generation",
                    }:
                        entry[key] = value
                message = str(error.get("message", "")).lower()
                entry["diagnostic_terms"] = [
                    term
                    for term in (
                        "schema",
                        "reference",
                        "$ref",
                        "$defs",
                        "tool call",
                        "function",
                        "failed to call",
                        "parameters",
                        "validation",
                        "tool choice",
                        "required",
                        "json",
                        "additionalproperties",
                    )
                    if term in message
                ]
            except (ValueError, KeyError, TypeError):
                pass
        self.responses.append(entry)

    def _request(self, instruction, data, span, **options):
        if self.calls >= self.limit:
            raise AgentProblem("LIVE_CALL_LIMIT", "Đã đạt giới hạn lượt gọi smoke.")
        self.calls += 1
        return super()._request(instruction, data, span, **options)


def snapshot(db):
    with closing(sqlite3.connect(db)) as conn:
        conn.row_factory = sqlite3.Row
        transactions = conn.execute(
            """
            SELECT u.username AS owner, t.id, t.transaction_date AS date, t.type, t.amount, c.name AS category
            FROM transactions t JOIN users u ON u.id=t.user_id JOIN categories c ON c.id=t.category_id ORDER BY t.id
        """
        ).fetchall()
        budgets = conn.execute(
            """
            SELECT u.username AS owner, c.name AS category, b.year, b.month, b.amount FROM budgets b
            JOIN users u ON u.id=b.user_id JOIN categories c ON c.id=b.category_id ORDER BY b.id
        """
        ).fetchall()
    return {"transactions": [dict(r) for r in transactions], "budgets": [dict(r) for r in budgets]}


def copy_db(source, dest):
    with closing(sqlite3.connect(source)) as src, closing(sqlite3.connect(dest)) as target:
        src.backup(target)


def read_evidence(path):
    if not path.is_file():
        raise Blocked(f"Chưa có {path.name}")
    raw = path.read_bytes()
    return raw.decode("utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig")


def prepare(root, live, use_rag, profile="full"):
    settings = isolated_settings(root, live=live)
    seed(settings, profile)
    with TestClient(create_app(settings, enable_chat=True)) as client:
        headers = login(client)
        health = client.get("/health")
        health.raise_for_status()
        docs = []
        if use_rag:
            for name, body in DOCUMENTS.items():
                print("Indexing", name, flush=True)
                docs.append(upload(client, headers, name, body))
                print(name, docs[-1]["indexing_status"], docs[-1]["error_code"], flush=True)
        vector = client.app.state.knowledge.vector
        return settings, docs, vector._model, health.json()


class Run:
    def __init__(self, directory, settings, model, case, llm, script, capture):
        self.directory, self.settings, self.model = directory, settings, model
        self.case, self.llm, self.script = case, llm, script
        self.capture = capture
        self.stack = ExitStack()
        self.steps, self.turns = [], []
        self.conversation = self.document = self.saved_draft = None
        if script:
            script.case = case["case_id"]
            script.inputs.clear()
            script.problem = None

    def start(self):
        self.client = self.stack.enter_context(
            TestClient(create_app(self.settings, enable_chat=True, llm=self.llm))
        )
        self.client.app.state.knowledge.vector._model = self.model
        self.headers = login(self.client)

    def step(self, action):
        i = len(self.capture.events)
        h, client = self.headers, self.client
        if action == "@restart":
            self.stack.close()
            self.start()
            self.steps.append({"action": action})
            return
        if action.startswith("@signin:"):
            self.headers = login(client, action.split(":")[1])
            return
        if action.startswith(("@http:", "@network:")):
            self.script.problem = "timeout" if "network" in action else int(action.split(":")[1])
            return
        if action.startswith("@upload:"):
            name, content = DELETED if action.endswith("deleted") else INJECTION
            obj = upload(client, h, name, content)
            self.document = obj["document_id"]
            self.steps.append({"action": action, "document": obj})
            check(obj["indexing_status"] == "ready", "Tài liệu thử chưa sẵn sàng")
            return
        if action == "@delete":
            response = client.delete(f"/api/knowledge/documents/{self.document}", headers=h)
        elif action == "@state":
            response = client.get(f"/api/chat/{self.saved_draft}/state", headers=h)
        elif action == "@budget":
            response = client.get("/api/budgets/status", headers=h, params={"year": 2026, "month": 11})
        elif action.startswith("@"):
            thread = self.turns[0]["thread_id"] if action == "@old" else self.saved_draft
            decision = "CANCEL" if action == "@cancel" else "CONFIRM"
            response = client.post(f"/api/chat/{thread}/confirm", headers=h, json={"decision": decision})
        else:
            response = client.post(
                "/api/chat", headers=h, json={"message": action, "conversation_id": self.conversation}
            )
        events = [e for e in self.capture.events[i:] if e["trace_id"] == response.headers["x-trace-id"]]
        body = response.json() if response.content else None
        step = {
            "action": action,
            "http": response.status_code,
            "trace_id": response.headers["x-trace-id"],
            "response": body,
            "events": [
                {
                    k: v
                    for k, v in e.items()
                    if v is not None and k not in {"trace_id", "thread_id", "timestamp"}
                }
                for e in events
                if e["event"] != "agent.node" or e["status"] != "OK"
            ],
            "nodes": [e["agent_node"] for e in events if e["event"] == "agent.node"],
        }
        self.steps.append(step)
        check(
            response.status_code == (409 if action == "@old" else 204 if action == "@delete" else 200),
            f"{action}: HTTP {response.status_code}",
        )
        if not action.startswith("@"):
            check(
                not self.conversation or body["conversation_id"] == self.conversation,
                "Conversation ID changed",
            )
            self.conversation = body["conversation_id"]
            self.turns.append(body)
            if body["status"] == "PENDING_CONFIRMATION":
                self.saved_draft = body["thread_id"]
        if not action.startswith("@") or action in {"@cancel", "@old", "@confirm", "@retry"}:
            step["sql_counts"] = self.counts()
        return body

    def counts(self):
        data = snapshot(self.directory / "demo.db")
        return {
            "transactions": len(data["transactions"]),
            "budgets": len(data["budgets"]),
            "budget_amounts": [r["amount"] for r in data["budgets"]],
        }

    def verify(self, before, after, today):
        cid = self.case["case_id"]
        turns, steps = self.turns, self.steps
        last = turns[-1]
        events = [e for s in steps for e in s.get("events", [])]
        tools = [e.get("tool_name") for e in events if e["event"] == "financial.tool" and e["status"] == "OK"]
        if cid.startswith("Q") or cid in {"D05", "D06", "D07", "B02", "G03", "G05", "G06"}:
            check(all(e["event"] != "rag.retrieval" for e in events), "Truy vấn tài khoản đã đi qua RAG")
        for expected in self.case["expected_tool"]:
            if expected == "rag":
                check(any(e["event"] == "rag.retrieval" for e in events), "Thiếu bước truy xuất RAG")
            else:
                check(expected in tools, f"Thiếu Financial Tool {expected}; thực tế {tools}")
        delta = self.case["expected_database_change"]
        n = int(delta[1:]) if delta.startswith("+") else 0
        check(len(after["transactions"]) == len(before["transactions"]) + n, "Sai số bản ghi SQLite")
        check(
            after["transactions"][: len(before["transactions"])] == before["transactions"],
            "Bản ghi cũ đã thay đổi",
        )
        check(
            after["budgets"] == before["budgets"] or delta.startswith("budget:"),
            "Ngân sách thay đổi ngoài yêu cầu",
        )
        for s in steps:
            if "sql_counts" in s and s["action"] not in {"@confirm", "@retry"}:
                previous = [p for p in steps[: steps.index(s)] if "sql_counts" in p]
                count = (
                    previous[-1]["sql_counts"]["transactions"] if previous else len(before["transactions"])
                )
                check(s["sql_counts"]["transactions"] == count, "Ghi giao dịch khi chưa xác nhận")
                limits = (
                    previous[-1]["sql_counts"]["budget_amounts"]
                    if previous
                    else [r["amount"] for r in before["budgets"]]
                )
                check(s["sql_counts"]["budget_amounts"] == limits, "Sửa ngân sách khi chưa xác nhận")
        if n:
            receipts = [
                s["response"]["structured_data"] for s in steps if s["action"] in {"@confirm", "@retry"}
            ]
            added = after["transactions"][-n:]
            check({r["id"] for r in receipts} == {r["id"] for r in added}, "Sai biên nhận hoặc ghi trùng")
            for r in receipts:
                row = next(a for a in added if a["id"] == r["id"])
                check(
                    row["owner"] == "demo_a"
                    and (row["amount"], row["date"]) == (r["amount"], r["transaction_date"]),
                    "Biên nhận khác SQLite",
                )
        if cid in {"D01", "C01", "C03"}:
            day = "20/11/2026" if cid == "C03" else today.strftime("%d/%m/%Y")
            check(day in last["message"], "Sai ngày Backend")
            if cid == "D01":
                check("ngân sách" in last["message"].lower(), "Thiếu trả lời về khả năng MoneyMind")
        elif cid in {"C02", "C04", "R05", "G04"}:
            check(last["status"] == "COMPLETED" and not last["sources"] and not tools, "Sai nhánh hội thoại")
            if cid == "C02":
                check("ngân sách" in last["message"].lower(), "Thiếu phạm vi tính năng")
            if cid == "G04":
                check(
                    self.script.inputs
                    and "123456789012" not in str(self.script.inputs) + str(events)
                    and "đã ẩn" in str(self.script.inputs),
                    "Masking chưa hoạt động",
                )
        elif cid in {"D02", "D03", "D04", "T01", "T02", "T03", "T04", "T05", "T07", "T09", "T10", "G08"}:
            amount, category, day = {
                "T01": (35000, "Ăn uống", today - timedelta(days=1)),
                "T02": (90000, "Mua sắm", "2026-11-20"),
                "T03": (200000, "Ăn uống", today - timedelta(days=1)),
                "T04": (90000, "Mua sắm", today - timedelta(days=1)),
                "T05": (70000, "Mua sắm", today - timedelta(days=2)),
                "T07": (12000000, "Lương", "2026-11-20"),
                "D04": (90000, "Mua sắm", "2026-11-22"),
                "T10": (90000, "Mua sắm", "2026-11-22"),
            }.get(cid, (50000, "Ăn uống", "2026-11-21"))
            draft = last.get("pending_action") or {}
            payload = draft.get("payload") or {}
            check(
                last["pending_state"] == "ready_for_confirmation"
                and draft.get("category") == category
                and (payload.get("amount"), payload.get("transaction_date"), payload.get("type"))
                == (amount, str(day), "INCOME" if category == "Lương" else "EXPENSE"),
                "Sai trường bản nháp",
            )
            if cid in {"D04", "T10", "T05"}:
                check(
                    turns[0]["pending_action"]["payload"]["amount"] == 70000 and last["draft_version"] == 2,
                    "Sai phiên bản",
                )
            if cid == "T03":
                check(
                    [t["error_code"] for t in turns[:2]] == ["AMOUNT_REQUIRED", "DATE_REQUIRED"],
                    "Mất trường đã thu thập",
                )
            if cid == "G08":
                check(
                    next(s["response"] for s in steps if s["action"] == "@state")["pending_action"] == draft,
                    "Mất bản nháp sau restart",
                )
        elif cid in {"T06", "T08", "T11", "B05", "D12", "G01", "G02"}:
            if cid == "T06":
                check(last["pending_state"] == "cancelled", "Hủy bản nháp thất bại")
            elif cid in {"D12", "G01", "G02"}:
                check(
                    last["error_code"] == ("ACCOUNT_SCOPE" if cid == "G02" else "INPUT_BLOCKED"),
                    "Guardrail chưa chặn",
                )
            else:
                codes = {"PLANNED_TRANSACTION"} if cid == "T08" else {"INVALID_AMOUNT", "AMOUNT_REQUIRED"}
                check(
                    all(t["error_code"] in codes and not t["pending_action"] for t in turns),
                    "Không từ chối số tiền/kế hoạch",
                )
        elif cid in {"D05", "Q02", "Q05", "Q08"}:
            for idx, t in enumerate(turns):
                period = "2026-11-21" if cid == "Q08" else ("2026-10" if idx else "2026-11")
                rows = [
                    r
                    for r in before["transactions"]
                    if r["owner"] == "demo_a" and r["date"].startswith(period)
                ]
                income, expense = [
                    sum(r["amount"] for r in rows if r["type"] == kind) for kind in ("INCOME", "EXPENSE")
                ]
                check(
                    t["financial_data"]
                    == {"total_income": income, "total_expense": expense, "net_cash_flow": income - expense},
                    "Tổng thu, chi hoặc dòng tiền sai so với SQLite",
                )
        elif cid in {"D06", "Q01", "Q04", "Q07", "G03", "G06"}:
            owner = "demo_b" if cid == "G03" else "demo_a"
            period = str(today) if cid in {"Q01", "G06"} else "2026-10" if cid == "Q07" else "2026-11-21"
            rows = [r for r in before["transactions"] if r["owner"] == owner and r["date"].startswith(period)]
            actual = last["financial_data"] or {}
            check(
                actual.get("total") == len(rows)
                and sorted((r["id"], r["amount"]) for r in actual["items"])
                == sorted((r["id"], r["amount"]) for r in rows)
                and not last["sources"],
                "Chi tiết khác SQLite",
            )
            if cid == "G03":
                check(
                    turns[0]["error_code"] == "ACCOUNT_SCOPE" and not turns[0]["financial_data"],
                    "Lộ dữ liệu khác tài khoản",
                )
        elif cid in {"D07", "Q03", "Q06", "B02", "D08", "B01", "B03", "B04"}:
            verify_finance(cid, turns, steps, after)
        elif cid in {"D09", "D10", "D11", "R01", "R02", "R03", "R04", "C05", "R06", "R07", "R08", "G07"}:
            verify_knowledge(cid, turns, steps, self.document, before, today)
        elif cid == "G05":
            check(
                turns[0]["status"] == "COMPLETED" and turns[0]["financial_data"]["total"] == 0,
                "400 không phục hồi đọc theo ngày",
            )
            check(
                turns[1]["error_code"] == "LLM_RATE_LIMIT" and "TIMEOUT" in turns[2]["error_code"],
                "Không phân loại lỗi",
            )
            check(
                any(
                    e.get("http_status") == 400 and e.get("provider_error_code") == "tool_use_failed"
                    for e in events
                ),
                "Trace thiếu HTTP status hoặc provider error code",
            )
        else:
            raise AssertionError(f"Chưa có kiểm chứng cho {cid}")


def verify_finance(cid, turns, steps, after):
    food = [
        r
        for r in after["transactions"]
        if r["owner"] == "demo_a" and r["category"] == "Ăn uống" and r["date"].startswith("2026-11")
    ]
    spent = sum(r["amount"] for r in food)
    if cid in {"B03", "B04"}:
        check(spent == {"B03": 170000, "B04": 210000}[cid], "Khoản ăn uống xác nhận khác fixture")
    if cid in {"D07", "Q03"}:
        check(
            [(r["category_name"], r["total_expense"]) for r in turns[0]["financial_data"]]
            == [("Ăn uống", spent)],
            "Bộ lọc danh mục sai",
        )
    if cid == "Q03":
        return
    if cid == "Q06":
        totals = Counter()
        for r in after["transactions"]:
            if r["owner"] == "demo_a" and r["type"] == "EXPENSE" and r["date"].startswith("2026-11"):
                totals[r["category"]] += r["amount"]
        check(
            [(r["category_name"], r["total_expense"]) for r in turns[0]["financial_data"]]
            == totals.most_common(3),
            "Thứ hạng danh mục sai",
        )
        return
    budget = next(
        r
        for r in after["budgets"]
        if r["owner"] == "demo_a" and r["category"] == "Ăn uống" and (r["year"], r["month"]) == (2026, 11)
    )
    data = turns[-1]["financial_data"] if cid in {"D07", "B02"} else steps[-1]["response"]
    check(len(data) == 1, "Sai phạm vi ngân sách")
    row = data[0]
    check(
        (row["amount"], row["spent"], row["remaining"], row["usage_percent"])
        == (200000, spent, budget["amount"] - spent, 100 * spent / budget["amount"]),
        "Số liệu ngân sách khác SQLite",
    )
    check(row["alert"] == {"B03": "WARNING", "B04": "EXCEEDED"}.get(cid, "NORMAL"), "Sai cảnh báo ngân sách")
    if cid in {"D08", "B01"}:
        check(
            steps[0]["response"]["pending_action"]["payload"]["amount"] == 200000
            and steps[1]["response"]["structured_data"]["id"] == row["id"],
            "Ngân sách thiếu xác nhận/biên nhận",
        )


def verify_knowledge(cid, turns, steps, document_id, before, today):
    last = turns[-1]
    if cid == "R08":
        check(
            last["status"] in {"ERROR", "NEEDS_CLARIFICATION"}
            and last["error_code"].startswith("RAG_")
            and not last["sources"]
            and "tải" in last["message"].lower(),
            "Thiếu hướng dẫn RAG trống",
        )
        return
    if cid == "R06":
        check(
            any(s["document_id"] == document_id for s in turns[0]["sources"]),
            "Chưa chứng minh file truy xuất được trước xóa",
        )
        check(not last["sources"] and last["error_code"] == "RAG_NO_CONTEXT", "Dẫn tài liệu sau khi xóa")
        return
    name = {
        "D10": "du-phong.md",
        "R02": "du-phong.md",
        "C05": "du-phong.md",
        "R03": "chi-khong-deu.md",
        "G07": INJECTION[0],
    }.get(cid, "phan-bo.md")
    allowed = {name, "chi-khong-deu.md"} if cid in {"D11", "R07"} else {name}
    for t, step in zip(turns, (s for s in steps if not s["action"].startswith("@")), strict=True):
        hits = {h for e in step["events"] for h in e.get("retrieved_chunk_ids", [])}
        check(
            t["status"] == "COMPLETED"
            and name in {s["original_filename"] for s in t["sources"]}
            and all(
                s["original_filename"] in allowed
                and s["chunk_id"] in hits
                and s["evidence"] in (DOCUMENTS.get(s["original_filename"]) or INJECTION[1])
                for s in t["sources"]
            ),
            "Nguồn/evidence chưa khớp file upload và trace truy xuất",
        )
        check(
            "[1]" in t["message"] and "api key" not in folded(t["message"]),
            "Citation hoặc xử lý chỉ dẫn tài liệu sai",
        )
        if cid in {"D09", "R01", "R04", "D11", "R07"}:
            advice = t["message"].split("Gợi ý từ tài liệu\n")[-1]
            lines = [
                re.sub(r"\s*\[\d+\]", "", l).strip("• ")
                for l in advice.splitlines()
                if re.search(r"\[\d+\]", l)
            ]
            check(
                any(line and all(line not in DOCUMENTS[n] for n in allowed) for line in lines),
                "Phần tư vấn chỉ sao chép nguyên câu từ tài liệu",
            )
        if cid in {"D09", "R01", "R04"}:
            check(all(str(n) in t["message"] for n in (50, 30, 20)), "Thiếu tỷ lệ phân bổ")
    if cid in {"D11", "R07"}:
        period = today.strftime("%Y-%m") if cid == "R07" else f"{today.year}-11"
        rows = [
            r
            for r in before["transactions"]
            if r["owner"] == "demo_a" and r["type"] == "EXPENSE" and r["date"].startswith(period)
        ]
        data = last["financial_data"]
        check(
            isinstance(data, list)
            and sum(r["total_expense"] for r in data) == sum(r["amount"] for r in rows)
            and (not rows or "90.000" in last["message"]),
            "Tư vấn thiếu số liệu SQLite theo kỳ",
        )


def metadata_case(cid, report, directory, label):
    index = {r["case_id"]: r for r in report["cases"]}
    if cid in {"O01", "O02", "D13"}:
        source_ids = {"O01": ["Q02"], "O02": ["R01"], "D13": ["D05", "D09"]}[cid]
        traces = []
        for source in source_ids:
            item = index.get(source)
            if not item or item["status"] != "PASS":
                raise Blocked(f"Thiếu bằng chứng PASS của {source}")
            step = item["steps"][0]
            events = step["events"]
            check(
                any(
                    e["event"] == "llm.request"
                    and e["requested_model"]
                    and e.get("response_model")
                    and e["latency_ms"] >= 0
                    for e in events
                ),
                "Trace thiếu model/latency",
            )
            check(
                any(
                    e["event"] == "agent.run" and e.get("intent") and e["status"] == "COMPLETED"
                    for e in events
                ),
                "Trace thiếu intent/status",
            )
            check(
                any(
                    (
                        e.get("tool_name") and e["status"] == "OK"
                        if source in {"Q02", "D05"}
                        else e.get("retrieved_chunk_ids")
                    )
                    for e in events
                ),
                "Trace thiếu tool/chunk",
            )
            traces.append({"source_case": source, "trace_id": step["trace_id"]})
        if cid == "D13":
            check(
                re.search(
                    r"MOCK_EVAL: [1-9]\d* PASS / 0 FAIL / 0 NOT_EVALUATED",
                    read_evidence(directory / f"{label}-mock.txt"),
                ),
                "Mock eval chưa đạt",
            )
        return traces
    if cid == "O03":
        output = read_evidence(directory / f"{label}-pytest.txt")
        check(
            re.search(r"\d+ passed", output) and not re.search(r"\d+ (?:failed|errors?)\b", output),
            "Pytest còn lỗi",
        )
        return [{"pytest": re.search(r"\d+ passed[^\r\n]*", output)[0]}]
    if cid == "O04":
        output = read_evidence(directory / f"{label}-quality.txt")
        if "NO_APPROVED_LABELS" in output:
            raise Blocked("NO_APPROVED_LABELS — chưa có nhãn test được người duyệt.")
        rows = [json.loads(line) for line in output.splitlines() if line.startswith("{")]
        retrieval = next((r for r in rows if "recall@3" in r and r.get("split") == "test"), None)
        answers = next((r for r in rows if r.get("answer_cases") and not r.get("missing_answers")), None)
        if not retrieval or not answers:
            raise Blocked("Cần kết quả retrieval và bộ câu trả lời cho toàn bộ nhãn test đã duyệt.")
        return [{"file": f"{label}-quality.txt", "retrieval": retrieval, "answers": answers}]
    live = json.loads(read_evidence(directory / f"{label}-live.json"))
    check(live.get("mode") == "live-groq", "O05 yêu cầu bằng chứng Groq thật")
    for c in live["cases"]:
        for s in c.get("steps", []):
            for e in s.get("events", []):
                if (
                    e["event"] == "llm.request"
                    and e.get("requested_model") == "openai/gpt-oss-120b"
                    and e.get("response_model") == "openai/gpt-oss-120b"
                    and e["status"] == "OK"
                ):
                    return [
                        {
                            "trace_id": s["trace_id"],
                            "requested_model": e["requested_model"],
                            "response_model": e["response_model"],
                        }
                    ]
    raise Blocked("Chưa có response_model từ Groq thật")


def run(args):
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    os.environ.setdefault("OMP_NUM_THREADS", "2")
    results = args.results.resolve()
    results.mkdir(parents=True, exist_ok=True)
    report = {
        "mode": "live-groq" if args.live else "mock-provider-real-sqlite-chroma",
        "started": datetime.now(UTC).isoformat(),
        "clock": "backend" if args.live else NOW.isoformat(),
        "cases": [],
    }
    path = results / f"{args.label}-{'live' if args.live else 'demo'}.json"

    capture = Capture()
    old_handlers, LOGGER.handlers = LOGGER.handlers, [capture]
    try:
        with tempfile.TemporaryDirectory(
            prefix="moneymind-demo-", ignore_cleanup_errors=True
        ) as temp, ExitStack() as stack:
            root = Path(temp)
            selected = (
                args.cases.split(",")
                if args.cases
                else (["Q01", "D05", "D04", "D09", "R07"] if args.live else [c["case_id"] for c in CATALOG])
            )
            cases = {c["case_id"]: c for c in CATALOG}
            settings, docs, model, health = prepare(
                root, args.live, any(cases[c]["requires_rag"] and c != "R08" for c in selected)
            )
            report.update(
                health=health,
                documents=docs,
                provider=settings.llm_provider,
                requested_model=settings.llm_model,
                reasoning_effort=settings.llm_reasoning_effort,
                embedding=settings.embedding_model,
            )
            script = None if args.live else Script()
            if args.live:
                if (settings.llm_provider, settings.llm_model, str(settings.llm_base_url).rstrip("/")) != (
                    "groq",
                    "openai/gpt-oss-120b",
                    "https://api.groq.com/openai/v1",
                ):
                    raise SystemExit("Live smoke requires the configured Groq baseline endpoint.")
                llm = LimitedGroq(settings, args.limit)
            else:
                llm = ChatCompletionsLLM(settings, transport=httpx.MockTransport(script), retry=False)
                stack.enter_context(patch("backend.app.agent.runtime.local_now", return_value=NOW))
            stack.enter_context(llm)
            blocked = None
            for cid in selected:
                case = cases[cid]
                row = {
                    "case_id": cid,
                    "status": "NOT_RUN",
                    "timestamp": datetime.now(UTC).isoformat(),
                    "steps": [],
                }
                report["cases"].append(row)
                try:
                    if blocked:
                        raise Blocked(blocked)
                    if args.live and cid in {"G04", "G05"}:
                        raise Blocked(
                            "Ca này cần quan sát payload hoặc chủ động mô phỏng lỗi qua mock transport."
                        )
                    if cid.startswith("O") or cid == "D13":
                        row["steps"] = metadata_case(cid, report, results, args.label)
                    else:
                        if (
                            case["requires_rag"]
                            and cid != "R08"
                            and not all(d["indexing_status"] == "ready" for d in docs)
                        ):
                            raise Blocked(
                                "RAG fixture index: "
                                + str([d["error_code"] for d in docs if d["error_code"]])
                            )
                        directory = root / cid
                        directory.mkdir()
                        db = directory / "demo.db"
                        empty = cid in {"G06", "R08"}
                        clone = settings.model_copy(
                            update={
                                "database_url": f"sqlite:///{db.as_posix()}",
                                "agent_checkpoint_path": directory / "graph.db",
                                **(
                                    {
                                        "rag_directory": directory / "chroma",
                                        "rag_upload_directory": directory / "uploads",
                                    }
                                    if empty
                                    else {}
                                ),
                            }
                        )
                        if empty:
                            seed(clone)
                        else:
                            copy_db(root / "demo.db", db)
                        if cid in {"D08", "B01"}:
                            with closing(sqlite3.connect(db)) as conn:
                                if cid == "D08":
                                    conn.execute(
                                        "DELETE FROM budgets WHERE user_id=(SELECT id FROM users WHERE username='demo_a')"
                                    )
                                else:
                                    conn.execute("UPDATE budgets SET amount=100000")
                                conn.commit()
                        run_case = Run(directory, clone, model, case, llm, script, capture)
                        row["steps"] = run_case.steps
                        today = local_now().date() if args.live else NOW.date()
                        row["backend_date"] = today.isoformat()
                        before = row["sql_before"] = snapshot(db)
                        try:
                            run_case.start()
                            for action in case["input_messages"]:
                                run_case.step(action)
                                if args.live:
                                    errors = [
                                        e.get("error_code")
                                        for s in run_case.steps
                                        for e in s.get("events", [])
                                        if e["event"] == "llm.request" and e["status"] == "ERROR"
                                    ]
                                    if any(
                                        err in INFRA or (err or "").startswith("LLM_NETWORK")
                                        for err in errors
                                    ):
                                        blocked = "Groq: " + str(errors[-1])
                                        raise Blocked(blocked)
                                if run_case.turns and run_case.turns[-1]["status"] == "ERROR" and args.live:
                                    raise AssertionError(run_case.turns[-1]["error_code"])
                            run_case.verify(before, snapshot(db), today)
                        finally:
                            row["sql_after"] = snapshot(db)
                            run_case.stack.close()
                    row["status"] = "PASS"
                except Blocked as error:
                    row.update(status="BLOCKED", reason=str(error))
                except Exception as error:
                    row.update(status="FAIL", reason=f"{type(error).__name__}: {error}"[:450])
                if args.live:
                    report["provider_attempts"] = llm.calls
                    report["provider_responses"] = llm.responses
                print(cid, row["status"], row.get("reason", ""), flush=True)
    finally:
        LOGGER.handlers = old_handlers
    report["counts"] = dict(Counter(r["status"] for r in report["cases"]))
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=results, delete=False) as output:
        json.dump(report, output, ensure_ascii=False, indent=1)
    Path(output.name).replace(path)
    print(report.get("counts"), path)
    return int(any(r["status"] == "FAIL" for r in report["cases"]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", default="final", choices=["baseline", "final"])
    parser.add_argument("--results", type=Path, default=HERE / "results")
    parser.add_argument(
        "--cases", help="Comma-separated IDs, in execution order; use another --results for subsets."
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Use the real Groq endpoint with only the isolated synthetic fixture.",
    )
    parser.add_argument("--limit", type=int, choices=range(1, 13), default=10)
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
