"""Opt-in Groq checks through authenticated FastAPI against disposable synthetic data."""

import argparse
import json
import os
import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.core.calendar import local_today, month_dates
from backend.app.core.formatting import money
from backend.app.core.observability import LOGGER
from backend.app.main import create_app
from evaluation.demo_fixture import DOCUMENTS, login
from evaluation.demo_run import Capture, LimitedGroq, prepare, snapshot

SCENARIOS = [
    ["Tôi nên quản lý chi tiêu tháng này như thế nào?"],
    ["Từ số liệu tháng 11 tôi nên chi tiêu như nào cho hợp lý?"],
    [
        "Với quy luật 50-30-20 thì nên chia như nào?",
        "Vậy với tôi thì nên chi như nào?",
        "Tháng trước thì sao?",
    ],
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument(
        "--spacing", type=int, default=18, help="Seconds between chat turns in the smoke run."
    )
    args = parser.parse_args()
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("OMP_NUM_THREADS", "2")
    report = {"mode": "live", "turns": []}
    capture = Capture()
    old, LOGGER.handlers = LOGGER.handlers, [capture]
    try:
        with tempfile.TemporaryDirectory(prefix="advisory-", ignore_cleanup_errors=True) as folder:
            root = Path(folder)
            settings, docs, model, _ = prepare(root, True, True)
            if not all(d["indexing_status"] == "ready" for d in docs):
                raise RuntimeError("RAG_FIXTURE_UNAVAILABLE")
            if (
                str(settings.llm_base_url).rstrip("/") != "https://api.groq.com/openai/v1"
                or settings.llm_model != "openai/gpt-oss-120b"
            ):
                raise RuntimeError("BASELINE_CONFIGURATION_REQUIRED")
            ledger = snapshot(root / "demo.db")["transactions"]
            today = local_today()
            with LimitedGroq(settings, 12) as llm, TestClient(
                create_app(settings, enable_chat=True, llm=llm)
            ) as client:
                client.app.state.knowledge.vector._model = model
                headers = login(client)
                for idx, prompts in enumerate(SCENARIOS):
                    cid = client.post("/api/chat/conversations", headers=headers).json()["conversation_id"]
                    for pos, prompt in enumerate(prompts):
                        if report["turns"]:
                            time.sleep(args.spacing)
                        r = client.post(
                            "/api/chat", headers=headers, json={"message": prompt, "conversation_id": cid}
                        )
                        body = r.json()
                        trace = r.headers["x-trace-id"]
                        events = [e for e in capture.events if e["trace_id"] == trace]
                        case = {
                            "question": prompt,
                            "response": body,
                            "trace_id": trace,
                            "events": [
                                e
                                for e in events
                                if e["event"] in {"financial.tool", "rag.retrieval", "llm.request"}
                            ],
                        }
                        report["turns"].append(case)
                        try:
                            assert body["status"] == "COMPLETED" and body["sources"], "no grounded answer"
                            for source in body["sources"]:
                                assert (
                                    source["evidence"] in DOCUMENTS[source["original_filename"]]
                                ), "invalid evidence"
                            if idx != 2 or pos:
                                scope = body["advisory_scope"]
                                month = 11 if idx == 1 else today.month
                                year = today.year
                                if idx == 2 and pos == 2:
                                    year, month = (year - 1, 12) if month == 1 else (year, month - 1)
                                first, last = month_dates(year, month)
                                assert (scope["start_date"], scope["end_date"]) == (
                                    str(first),
                                    str(last),
                                ), "wrong period"
                                entries = [
                                    t
                                    for t in ledger
                                    if t["owner"] == "demo_a" and str(first) <= t["date"] <= str(last)
                                ]
                                income, spent = (
                                    sum(t["amount"] for t in entries if t["type"] == k)
                                    for k in ("INCOME", "EXPENSE")
                                )
                                assert (
                                    money(spent) in body["message"] and money(income) in body["message"]
                                ), "wrong amounts"
                                assert {"get_financial_summary", "get_spending_by_category"} <= {
                                    e["tool_name"] for e in events
                                }
                                if idx == 2:
                                    assert (
                                        money(income // 2) in body["message"]
                                        and money(income * 30 // 100) in body["message"]
                                        if income
                                        else "mức thu nhập nào" in body["message"]
                                    ), "allocation missing"
                            case["status"] = "PASS"
                        except (AssertionError, KeyError, TypeError) as err:
                            infra = body.get("error_code") in {
                                "LLM_RATE_LIMIT",
                                "LLM_UNAVAILABLE",
                                "LLM_TIMEOUT",
                                "LLM_AUTH_ERROR",
                                "LLM_NETWORK_DENIED",
                                "LIVE_CALL_LIMIT",
                            }
                            case.update(status="BLOCKED" if infra else "FAIL", reason=str(err))
                report["provider_attempts"] = llm.calls
    finally:
        LOGGER.handlers = old
        path = Path(__file__).parent / "results" / "advisory-live.json"
        path.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf8")
    print([t["status"] for t in report["turns"]])
    return int(any(t["status"] != "PASS" for t in report["turns"]))


if __name__ == "__main__":
    raise SystemExit(main())
