from backend.app.agent.guardrails import validate_action
from backend.app.agent.llm import AgentProblem, ChatCompletionsLLM
from backend.app.agent.rag import ChromaKnowledge, KNOWLEDGE_DIRECTORY
from backend.app.agent.rag_answer import generate_grounded
from backend.app.agent.statistics import READ_TOOLS, tool_definitions
from backend.app.agent.workflow import CLASSIFY, EXTRACT, SELECT_TOOL
from backend.app.core.calendar import local_today
from backend.app.core.config import Settings
from backend.app.schemas.chat import IntentOutput, PendingTransaction, TransactionExtraction
from backend.app.schemas.finance import CategoryView

RAG_CASES = (
    ("emergency_fund", "Quỹ dự phòng là gì và nên giữ ở đâu?", "quy-du-phong"),
    ("rule_50_30_20", "Quy tắc 50/30/20 chia thu nhập như thế nào?", "quy-tac-50-30-20"),
    ("debt", "Nên làm gì khi khó thanh toán khoản nợ vào ngày đến hạn?", "quan-ly-no"),
    ("irrelevant", "Loài sao biển di chuyển bằng gì?", None),
)


def evaluate_rag(settings: Settings) -> list[tuple[str, bool | None]]:
    if not any(KNOWLEDGE_DIRECTORY.glob("*.md")):
        return [(name + " (REFERENCE_CORPUS_MISSING)", None) for name, _, _ in RAG_CASES]
    knowledge = ChromaKnowledge(settings)
    results = []
    for name, question, expected in RAG_CASES:
        ranked = knowledge.rank(question)
        kept = [chunk.source for chunk, score in ranked if score >= settings.rag_min_similarity]
        passed = (
            any(source.document_id == expected and bool(source.title and source.source) for source in kept)
            if expected else not kept
        )
        top = ranked[0][1] if ranked else 0
        results.append((f"{name} (top cosine {top:.3f})", passed))
    return results


def evaluate_llm(settings: Settings) -> list[tuple[str, bool | None]]:
    llm = ChatCompletionsLLM(settings, retry=False)
    today = local_today()
    question = "Quỹ dự phòng là gì?"
    text = "Ăn sáng 35k hôm nay"
    category = CategoryView(id=1, name="Ăn uống", type="EXPENSE")
    results = []

    def check(name, test):
        try:
            results.append((name, bool(test())))
        except AgentProblem as error:
            results.append((f"{name} ({error.code})", False))
        except ValidationError:
            results.append((f"{name} (INVALID_SCHEMA)", False))

    def transaction():
        extraction = llm.structured(TransactionExtraction, EXTRACT, {
            "message": text, "today": today.isoformat(), "categories": [{"name": category.name, "type": category.type}],
        })
        pending = validate_action(text, extraction, [category], today)
        return isinstance(pending, PendingTransaction) and pending.payload.amount == 35_000 and pending.payload.transaction_date == today

    def statistics():
        call = llm.select_tool(SELECT_TOOL, {
            "message": "Cho tôi tổng thu và tổng chi của tất cả thời gian.",
            "today": today.isoformat(), "categories": [category.name],
        }, tool_definitions())
        if call.name != "get_financial_summary":
            return False
        schema, _ = READ_TOOLS[call.name]
        return schema.model_validate(call.arguments).model_dump(exclude_none=True) == {}

    check("transaction_extraction", transaction)
    check("statistics_tool", statistics)
    check("advice_intent", lambda: llm.structured(IntentOutput, CLASSIFY, {"message": question}).intent == "FINANCIAL_ADVICE")
    if not (KNOWLEDGE_DIRECTORY / "quy-du-phong.md").is_file():
        results.append(("advice_grounding (REFERENCE_CORPUS_MISSING)", None))
        llm.close()
        return results
    try:
        chunks = ChromaKnowledge(settings).retrieve(question)
    except AgentProblem as error:
        results.append((f"advice_grounding ({error.code})", None))
    else:
        def grounding():
            answer = generate_grounded(llm, question, chunks)
            return "quy-du-phong" in {source.document_id for source in answer.sources}

        check("advice_grounding", grounding)
    llm.close()
    return results

from pydantic import ValidationError

