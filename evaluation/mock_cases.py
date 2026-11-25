from datetime import date
from pathlib import Path
from secrets import token_urlsafe
from tempfile import TemporaryDirectory

from sqlalchemy.orm import Session

from backend.app.agent.llm import ToolCall
from backend.app.agent.rag import Chunk
from backend.app.agent.runtime import ChatRuntime, ThreadNotFound
from backend.app.core.config import Settings
from backend.app.core.database import initialize_database, make_engine
from backend.app.models.finance import User
from backend.app.repositories.users import find_user_by_username
from backend.app.schemas.chat import (
    DialogueUpdate, GeneralReply, GroundedAnswer, IntentOutput, PendingTransaction, TransactionExtraction,
    Source, TransactionProposal,
)
from backend.app.schemas.finance import BudgetQuery, FinancialSummary, TransactionQuery
from backend.app.tools.finance import FinancialTools
from evaluation.demo_fixture import DOCUMENTS
from scripts.seed_demo import seed_data

SEED_DATE = date(2024, 2, 15)
WRITE_DATE = date(2024, 2, 29)
FEBRUARY = {"start_date": "2024-02-01", "end_date": "2024-02-29"}


def scripted_dialogue(action="new_request", *, field=None, needs_clarification=False, **changes):
    return DialogueUpdate.model_validate({
        "action": action, "clarification_field": field, "needs_clarification": needs_clarification,
        "changes": {
            "amount_text": None, "date_text": None, "category": None, "type": None, "note": None,
            "clear_note": False, "timing": None, **changes,
        },
    })


class ScriptedLLM:
    def __init__(self):
        self.intent = "CREATE_TRANSACTION"
        self.extraction = {}
        self.tool = ToolCall("get_financial_summary", FEBRUARY)
        self.sources = []

    def structured(self, schema, instruction, data):
        if schema is IntentOutput:
            return schema(intent=self.intent)
        if schema is DialogueUpdate:
            return scripted_dialogue()
        if schema is TransactionProposal:
            return schema.model_validate({"timing": "actual", **self.extraction})
        if schema is GeneralReply:
            return schema(message="Có một chú mèo hay mang sách ra vườn đọc.")
        if schema is GroundedAnswer:
            context = {item["chunk_id"]: item["text"] for item in data["context"]}
            return schema.model_validate({
                "coverage": "full" if self.sources else "none",
                "statements": [
                    {"chunk_id": key, "text": context.get(key, "Nguồn không tồn tại."),
                     "evidence": context.get(key, "Nguồn không tồn tại.")}
                    for key in self.sources
                ],
            })
        return schema.model_validate(self.extraction)

    def select_tool(self, instruction, data, tools):
        return self.tool


class StaticRetriever:
    def __init__(self):
        self.matches: list[Chunk] = []

    def retrieve(self, question):
        return self.matches


def run(graph: ChatRuntime, llm: ScriptedLLM, retriever: StaticRetriever, owner: User, other: User) -> list[tuple[str, bool]]:
    results = []

    def check(name, condition):
        results.append((name, bool(condition)))

    def target_transactions() -> int:
        with Session(graph.engine) as session:
            tools = FinancialTools(session, authenticated_user_id=owner.id)
            return tools.list_transactions(
                TransactionQuery(start_date=WRITE_DATE, end_date=WRITE_DATE)
            ).total

    llm.intent = "UNKNOWN"
    story = graph.start(owner.id, "Kể tôi một câu chuyện")
    check("intent.general_conversation", story.status == "COMPLETED" and "chú mèo" in story.message)
    llm.intent = "CREATE_TRANSACTION"
    llm.extraction = TransactionExtraction(
        type="EXPENSE", amount_text="1tr2", category="Ăn uống", date_text="29/02/2024",
        note="Ăn sáng", multiple=False,
    ).model_dump()
    draft = graph.start(owner.id, "Ăn sáng 1tr2 ngày 29/02/2024")
    check("intent.transaction_route", draft.status == "PENDING_CONFIRMATION")
    action = draft.pending_action
    check("extraction.amount_date_category", isinstance(action, PendingTransaction) and action.category == "Ăn uống"
          and action.payload.amount == 1_200_000 and action.payload.transaction_date == WRITE_DATE)
    check("hitl.pending_has_no_write", target_transactions() == 0)
    if draft.status == "PENDING_CONFIRMATION":
        saved = graph.confirm(owner.id, draft.thread_id, "CONFIRM")
        replay = graph.confirm(owner.id, draft.thread_id, "CONFIRM")
        check("hitl.confirm_and_replay", saved.structured_data is not None and saved == replay
              and target_transactions() == 1)
    else:
        check("hitl.confirm_and_replay", False)

    missing_date = graph.start(owner.id, "Ăn sáng 1tr2")
    check("extraction.missing_date", missing_date.error_code == "DATE_REQUIRED")
    multiple = graph.start(owner.id, "Ăn sáng 1tr2 và ăn trưa 50k ngày 29/02/2024")
    check("guardrails.multiple_writes", multiple.error_code == "MULTIPLE_ACTIONS")

    llm.intent = "QUERY_STATISTICS"
    read = graph.start(other.id, "Tổng thu chi tháng 2/2024")
    check("tools.summary_read", read.status == "COMPLETED" and isinstance(read.financial_data, FinancialSummary))
    check("finance.scoped_totals", read.financial_data == FinancialSummary(
        total_income=18_000_000, total_expense=1_270_000, net_cash_flow=16_730_000,
    ))
    llm.tool = ToolCall("get_financial_summary", {"user_id": owner.id})
    check("guardrails.tool_arguments", graph.start(other.id, "Tổng chi?").error_code == "INVALID_TOOL_ARGUMENTS")

    llm.intent = "SET_BUDGET"
    llm.extraction = {
        "amount_text": "1 triệu", "category": "Ăn uống", "period_text": "tháng 3/2024", "multiple": False,
    }
    budget = graph.start(owner.id, "Đặt hạn mức ăn uống 1 triệu tháng 3/2024")
    try:
        graph.confirm(other.id, budget.thread_id, "CONFIRM")
        inaccessible = False
    except ThreadNotFound:
        inaccessible = True
    check("guardrails.thread_ownership", inaccessible)
    if budget.status == "PENDING_CONFIRMATION":
        canceled = graph.confirm(owner.id, budget.thread_id, "CANCEL")
        with Session(graph.engine) as session:
            tools = FinancialTools(session, authenticated_user_id=owner.id)
            check("hitl.cancel_budget", canceled.status == "COMPLETED" and canceled.structured_data is None
                  and tools.get_budget_status(BudgetQuery(year=2024, month=3)) == [])
    else:
        check("hitl.cancel_budget", False)

    llm.intent = "FINANCIAL_ADVICE"
    filename = "du-phong.md"
    heading, _, paragraph = DOCUMENTS[filename].partition("\n")
    chunk = Chunk("demo-du-phong:1", paragraph, Source(
        document_id="demo-du-phong", title=heading.removeprefix("# "), source=filename,
    ))
    retriever.matches, llm.sources = [chunk], [chunk.chunk_id]
    answer = graph.start(owner.id, "Quỹ dự phòng là gì?")
    check("rag.retrieved_source", answer.message == f"{chunk.text} [1]"
          and [source.chunk_id for source in answer.sources] == [chunk.chunk_id])
    llm.sources = ["outside_context"]
    blocked = graph.start(owner.id, "Quỹ dự phòng là gì?")
    check("rag.reject_fabricated_source", blocked.error_code == "RAG_SOURCE_INVALID" and not blocked.sources)
    return results


def evaluate_mock() -> list[tuple[str, bool]]:
    with TemporaryDirectory() as temp:
        settings = Settings(
            _env_file=None, auth_secret_key=token_urlsafe(48), app_env="test", langsmith_tracing=False,
            database_url=f"sqlite:///{(Path(temp) / 'eval.db').as_posix()}",
            agent_checkpoint_path=Path(temp) / "checkpoints.db",
        )
        engine = make_engine(settings.database_url)
        try:
            initialize_database(engine)
            with Session(engine, expire_on_commit=False) as session, session.begin():
                seed_data(session, SEED_DATE)
                owner = find_user_by_username(session, "demo_a")
                other = find_user_by_username(session, "demo_b")
            llm, retriever = ScriptedLLM(), StaticRetriever()
            graph = ChatRuntime(engine, settings, llm, retriever)
            try:
                return run(graph, llm, retriever, owner, other)
            finally:
                graph.close()
        finally:
            engine.dispose()
