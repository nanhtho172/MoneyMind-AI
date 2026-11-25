import argparse

from pydantic import ValidationError

from backend.app.agent.llm import AgentProblem
from backend.app.core.config import Settings
from evaluation.live_cases import evaluate_llm, evaluate_rag
from evaluation.mock_cases import evaluate_mock


def report(name: str, cases: list[tuple[str, bool | None]]) -> int:
    for label, result in cases:
        status = "NOT_EVALUATED" if result is None else "PASS" if result else "FAIL"
        print(f"{name} {status} {label}")
    passed = sum(result is True for _, result in cases)
    failed = sum(result is False for _, result in cases)
    skipped = len(cases) - passed - failed
    print(f"{name}: {passed} PASS / {failed} FAIL / {skipped} NOT_EVALUATED")
    return failed


def main() -> int:
    parser = argparse.ArgumentParser(description="MoneyMind software, provider, and retrieval evaluations.")
    parser.add_argument("--live-llm", action="store_true", help="Run up to four explicit provider requests.")
    parser.add_argument("--live-rag", action="store_true", help="Evaluate the local index with the real embedding model.")
    args = parser.parse_args()
    try:
        mock_results = evaluate_mock()
    except Exception:
        mock_results = [("evaluation_runner", False)]
    failures = report("MOCK_EVAL", mock_results)

    try:
        settings = Settings()
    except ValidationError:
        settings = None
    if not args.live_llm:
        print("LIVE_LLM_EVAL: NOT_EVALUATED (enable --live-llm)")
    elif settings is None or not (settings.llm_api_key and settings.llm_api_key.get_secret_value().strip()):
        print("LIVE_LLM_EVAL: NOT_EVALUATED (BLOCKED_BY_CONFIG)")
    else:
        failures += report("LIVE_LLM_EVAL", evaluate_llm(settings))

    if not args.live_rag:
        print("LIVE_RAG_EVAL: NOT_EVALUATED (enable --live-rag)")
    elif settings is None:
        print("LIVE_RAG_EVAL: NOT_EVALUATED (BLOCKED_BY_CONFIG)")
    else:
        try:
            failures += report("LIVE_RAG_EVAL", evaluate_rag(settings))
        except AgentProblem as error:
            if error.code in {"RAG_NOT_INITIALIZED", "RAG_MODEL_UNAVAILABLE", "RAG_DEPENDENCIES_MISSING"}:
                print(f"LIVE_RAG_EVAL: NOT_EVALUATED ({error.code})")
            else:
                failures += report("LIVE_RAG_EVAL", [(error.code, False)])
    return int(failures != 0)


if __name__ == "__main__":
    raise SystemExit(main())
