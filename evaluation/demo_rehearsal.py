"""Rehearse the presentation in order on one fresh ledger with the scripted provider."""

import argparse
import json
import os
import tempfile
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import httpx

from backend.app.agent.llm import ChatCompletionsLLM
from backend.app.core.observability import LOGGER
from evaluation.demo_fixture import ENTRIES
from evaluation.demo_provider import Script
from evaluation.demo_run import CATALOG, HERE, NOW, Capture, Run, check, prepare, snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=HERE / "results")
    dest = parser.parse_args().results / "stage-walkthrough.json"
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("OMP_NUM_THREADS", "2")
    capture = Capture()
    original, LOGGER.handlers = LOGGER.handlers, [capture]
    evidence = {
        "mode": "mock-provider-real-sqlite-chroma",
        "clock": NOW.isoformat(),
        "timestamp": datetime.now(UTC).isoformat(),
        "profile": "stage",
        "cases": [],
    }
    try:
        with tempfile.TemporaryDirectory(
            prefix="moneymind-stage-", ignore_cleanup_errors=True
        ) as folder, ExitStack() as stack:
            root = Path(folder)
            settings, docs, model, _ = prepare(root, False, True, profile="stage")
            check(all(d["indexing_status"] == "ready" for d in docs), "Fixture upload chưa sẵn sàng")
            script = Script()
            llm = stack.enter_context(
                ChatCompletionsLLM(settings, transport=httpx.MockTransport(script), retry=False)
            )
            stack.enter_context(patch("backend.app.agent.runtime.local_now", return_value=NOW))
            catalog = {c["case_id"]: c for c in CATALOG}
            run = Run(root, settings, model, catalog["D01"], llm, script, capture)
            stack.callback(run.stack.close)
            run.start()
            db = root / "demo.db"
            evidence["initial"] = snapshot(db)
            # D03 starts with the D02 draft and continues with Cancel, a new draft, Confirm and retry.
            for cid in ("D01", "D03", "D04", "D05", "D06", "Q01", "D08", "D07", "D09", "D10", "D11", "D12"):
                run.case, script.case = catalog[cid], cid
                fresh = run.client.post("/api/chat/conversations", headers=run.headers)
                fresh.raise_for_status()
                run.conversation = fresh.json()["conversation_id"]
                run.steps, run.turns, run.saved_draft = [], [], None
                row = {"case_id": cid, "steps": run.steps, "status": "FAIL"}
                evidence["cases"].append(row)
                before = snapshot(db)
                for action in run.case["input_messages"]:
                    run.step(action)
                run.verify(before, snapshot(db), NOW.date())
                row["status"] = "PASS"
            end = evidence["final"] = snapshot(db)
            actual = sorted(
                (t["category"], t["type"], t["amount"], t["date"])
                for t in end["transactions"]
                if t["owner"] == "demo_a"
            )
            expected = sorted((cat, kind, amount, f"2026-11-{day}") for cat, kind, amount, day, _ in ENTRIES)
            check(actual == expected, "Sổ cuối buổi diễn khác FIX-01–04")
            check([b["amount"] for b in end["budgets"] if b["owner"] == "demo_a"] == [200000], "Sai FIX-05")
            evidence["status"] = "PASS"
    except Exception as error:
        evidence.update(status="FAIL", reason=f"{type(error).__name__}: {error}"[:450])
    finally:
        LOGGER.handlers = original
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(evidence, ensure_ascii=False, indent=1), encoding="utf-8")
    print(evidence["status"], dest)
    return int(evidence["status"] != "PASS")


if __name__ == "__main__":
    raise SystemExit(main())
