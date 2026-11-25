import argparse
import json
import re
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from tempfile import TemporaryDirectory

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from backend.app.agent.guardrails import folded
from backend.app.agent.llm import AgentProblem
from backend.app.agent.rag import ChromaKnowledge, Chunk, load_documents
from backend.app.core.config import Settings
from backend.app.core.database import make_engine
from backend.app.schemas.chat import ChatResponse
from evaluation.rag_development import PROBES

_DIRECTORY = Path(__file__).resolve().parent
_DATASET_NAME = "rag_eval_draft.jsonl"
_RETRIEVAL_BEHAVIORS = {"answer", "abstain_no_source"}
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*(?:\s*%)?")


@dataclass(frozen=True)
class Case:
    id: str
    question: str
    expected: set[str]
    behavior: str
    facts: tuple[str, ...] = ()
    forbidden: tuple[str, ...] = ()


def find_dataset() -> Path | None:
    return next((
        file for directory in ("rag_test_pack", "datasets")
        if (file := _DIRECTORY / directory / _DATASET_NAME).is_file()
    ), None)


def load_approved(path: Path, split: str) -> tuple[list[Case], int, int]:
    result, pending, routed = [], 0, 0
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row["split"] != split:
            continue
        if row["review_status"] != "approved":
            pending += 1
            continue
        if row["expected_behavior"] not in _RETRIEVAL_BEHAVIORS:
            routed += 1
            continue
        result.append(Case(
            row["id"], row["question"], set(row["expected_document_ids"]), row["expected_behavior"],
            tuple(row.get("expected_facts", ())), tuple(row.get("forbidden_claims", ())),
        ))
    return result, pending, routed


def retrieval_metrics(cases: list[Case], results: dict[str, list[tuple[Chunk, float]]], threshold: float) -> dict:
    positive = [case for case in cases if case.expected]
    negative = [case for case in cases if case.behavior == "abstain_no_source"]
    ranked = {
        key: [chunk.source.document_id for chunk, score in chunks if score >= threshold]
        for key, chunks in results.items()
    }
    recalls = {}
    for k in (3, 5):
        for case in positive:
            matches = set(ranked[case.id][:k]) & case.expected
            recalls.setdefault(k, []).append(len(matches) / len(case.expected))
    ranks = [
        next((position for position, doc in enumerate(ranked[case.id][:5], 1) if doc in case.expected), None)
        for case in positive
    ]
    return {
        "threshold": threshold, "positive": len(positive), "abstain": len(negative),
        "recall@3": mean(recalls[3]) if positive else None,
        "recall@5": mean(recalls[5]) if positive else None,
        "hit_rate@3": mean(value > 0 for value in recalls[3]) if positive else None,
        "hit_rate@5": mean(rank is not None for rank in ranks) if positive else None,
        "mrr@5": mean(1 / rank if rank else 0 for rank in ranks) if positive else None,
        "retrieval_abstention": mean(not ranked[case.id] for case in negative) if negative else None,
    }


def _matchable(text: str) -> str:
    return " ".join(re.findall(r"\w+", folded(text)))


def answer_signals(case: Case, response: ChatResponse, retrieved: list[Chunk]) -> dict:
    claimed = response.status == "COMPLETED" and bool(response.sources)
    expected_answer = case.behavior == "answer"
    by_id = {row.chunk_id: row for row in retrieved}
    anchors = [
        source.chunk_id in by_id and by_id[source.chunk_id].source.document_id == source.document_id
        and bool(source.evidence)
        and " ".join(source.evidence.split()) in " ".join(by_id[source.chunk_id].text.split())
        for source in response.sources
    ]
    def numeric(text):
        return {value.replace(" ", "") for value in _NUMBER.findall(text)}

    answer = _matchable(response.message) if claimed else ""
    matched = sum(bool(_matchable(fact)) and _matchable(fact) in answer for fact in case.facts)
    forbidden = [claim for claim in case.forbidden if _matchable(claim) and _matchable(claim) in answer]
    markers = list(re.finditer(r"\[(\d+)\]", response.message))
    cites = bool(anchors) and all(anchors) and {int(match[1]) for match in markers} == set(range(1, len(anchors) + 1))
    numbers_grounded, start = True, 0
    if cites:
        for match in markers:
            source = response.sources[int(match[1]) - 1]
            numbers_grounded &= numeric(response.message[start:match.start()]) <= numeric(source.evidence or "")
            start = match.end()
        numbers_grounded &= not numeric(response.message[start:])
    abstained = response.status == "NEEDS_CLARIFICATION" and response.error_code == "RAG_NO_CONTEXT"
    return {
        "id": case.id,
        "relevance_signal": bool(matched) if case.facts else None,
        "faithfulness_checks": cites and numbers_grounded and not forbidden if claimed else None,
        "citation_correctness": cites and (
            not case.expected or any(source.document_id in case.expected for source in response.sources)
        ) if claimed else None,
        "completeness_literal": matched / len(case.facts) if case.facts else None,
        "abstention_correct": claimed if expected_answer else abstained,
        "manual_review_semantic": expected_answer,
    }


def _print(data: dict) -> None:
    print(json.dumps(data, ensure_ascii=True))


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate approved RAG labels or the separate development corpus.")
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--split", choices=("dev", "test"), default="test")
    parser.add_argument("--dev-baseline", action="store_true", help="Run separate built-in development probes.")
    parser.add_argument("--answers", type=Path, help="JSONL entries with id and response (ChatResponse).")
    parser.add_argument("--thresholds", nargs="+", type=float, help="Development only; report each candidate threshold.")
    args = parser.parse_args()
    if args.thresholds and not (args.dev_baseline or args.split == "dev"):
        parser.error("Threshold comparison is restricted to development.")
    if args.thresholds and any(not 0 <= value <= 1 for value in args.thresholds):
        parser.error("Thresholds must be between 0 and 1.")

    if args.dev_baseline:
        chunks = load_documents()
        if not chunks:
            _print({"status": "NOT_EVALUATED", "reason": "REFERENCE_CORPUS_MISSING"})
            return 0
        cases = [
            Case(key, question, {doc} if doc else set(), "answer" if doc else "abstain_no_source")
            for key, question, doc in PROBES
        ]
        split = "engineer_dev"
    else:
        path = args.dataset or find_dataset()
        if path is None or not path.is_file():
            _print({"status": "NOT_EVALUATED", "reason": "DATASET_NOT_FOUND"})
            return 0
        cases, pending, routed = load_approved(path, args.split)
        _print({"dataset": str(path), "split": args.split, "unapproved": pending, "routing_cases": routed})
        if not cases:
            _print({"status": "NOT_EVALUATED", "reason": "NO_APPROVED_LABELS"})
            return 0
        split = args.split

    try:
        settings = Settings()
    except ValidationError:
        _print({"status": "NOT_EVALUATED", "reason": "RAG_CONFIG_INVALID"})
        return 1
    with ExitStack() as resources:
        try:
            if args.dev_baseline:
                directory = resources.enter_context(TemporaryDirectory(ignore_cleanup_errors=True))
                knowledge = ChromaKnowledge(settings.model_copy(update={"rag_directory": Path(directory)}))
                knowledge.ingest(chunks)
            else:
                engine = make_engine(settings.database_url)
                resources.callback(engine.dispose)
                knowledge = ChromaKnowledge(settings, engine)
            results = {case.id: knowledge.rank(case.question, top_k=5) for case in cases}
        except AgentProblem as error:
            _print({"status": "NOT_EVALUATED", "reason": error.code})
            return 1
        except SQLAlchemyError:
            _print({"status": "NOT_EVALUATED", "reason": "KNOWLEDGE_DB_UNAVAILABLE"})
            return 1
    for threshold in args.thresholds or [settings.rag_min_similarity]:
        _print({"split": split, **retrieval_metrics(cases, results, threshold)})

    if args.answers:
        responses = {}
        for line in args.answers.read_text(encoding="utf-8-sig").splitlines():
            if line.strip():
                row = json.loads(line)
                responses[row["id"]] = ChatResponse.model_validate(row["response"])
        judged = []
        for case in cases:
            if case.id in responses:
                visible = [row for row, score in results[case.id][:settings.rag_top_k] if score >= settings.rag_min_similarity]
                signals = answer_signals(case, responses[case.id], visible)
                judged.append(signals)
                _print(signals)
        if judged:
            averages = {}
            for key in ("relevance_signal", "faithfulness_checks", "citation_correctness",
                        "completeness_literal", "abstention_correct"):
                values = [item[key] for item in judged if item[key] is not None]
                averages[key] = mean(values) if values else None
            _print({"answer_cases": len(judged), "missing_answers": len(cases) - len(judged), **averages})
        else:
            _print({"answer_evaluation": "NOT_EVALUATED", "reason": "NO_MATCHING_ANSWERS"})
    else:
        _print({"answer_evaluation": "NOT_EVALUATED", "reason": "NO_ANSWER_ARTIFACT"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
