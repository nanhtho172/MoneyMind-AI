import re
from datetime import date

from backend.app.agent.conversation import (
    ADVISORY_DOMAINS,
    ALLOCATION_RULE,
    APPLICATION,
    REFERENCE,
    is_follow_up,
    time_follow_up,
)
from backend.app.agent.guardrails import folded
from backend.app.core.formatting import money
from backend.app.schemas.chat import Source


def reference_topic(message: str, history: list[dict]) -> tuple[str, dict]:
    """Resolve the reference within the current conversation; preserve the stored user turn."""
    norm = folded(message)
    prior = history[-1] if history else {}
    carry = prior.get("intent") in ADVISORY_DOMAINS | {"QUERY_STATISTICS"} and (
        is_follow_up(norm)
        or time_follow_up(norm)
        or REFERENCE.search(norm)
        or APPLICATION.search(norm)
        and not re.search(r"\b(?:quy tac|quy luat)\b", norm)
    )
    scope = prior.get("advisory_scope", {}) if carry else {}
    previous = scope.get("topic") or (prior.get("user", "") if carry else "")
    if ALLOCATION_RULE.search(norm) or (carry and ALLOCATION_RULE.search(folded(previous))):
        topic = "Quy tắc 50/30/20 phân bổ thu nhập cho nhu cầu thiết yếu, mong muốn và tiết kiệm như thế nào?"
    elif (
        previous
        and prior["intent"] in ADVISORY_DOMAINS
        and (is_follow_up(norm) or APPLICATION.search(norm) or REFERENCE.search(norm))
    ):
        topic = previous
    elif re.search(r"\b(?:chi tieu|khoan chi)\b", norm) and not re.search(
        r"\b(?:quy du phong|tra no|no vay)\b", norm
    ):
        topic = "Nguyên tắc quản lý chi tiêu và rà soát khoản chi lớn. " + message
    else:
        topic = message
    return topic[:1000], scope


def spending_observation(rows, summary, start: date, end: date) -> str:
    lines = [
        f"Kỳ thống kê {start:%d/%m/%Y} – {end:%d/%m/%Y}.",
        f"Sổ giao dịch ghi nhận thu {money(summary.total_income)}, chi {money(summary.total_expense)}.",
    ]
    if rows:
        leader = rows[0]
        share = round(100 * leader.total_expense / summary.total_expense, 1) if summary.total_expense else 0
        lines.append(
            f"{leader.category_name} đứng đầu trong các nhóm được xem: "
            f"{money(leader.total_expense)}, chiếm {share:g}% tổng chi trong kỳ."
        )
    return "\n".join(lines)


def allocation(income: int, sources: list[Source]) -> str:

    evidence = " ".join(folded(s.evidence or "") for s in sources)
    labels = ("nhu cau thiet yeu|chi thiet yeu|nhu cau can thiet", "mong muon|so thich", "tiet kiem")
    for rate, label in zip((50, 30, 20), labels, strict=True):
        if not re.search(rf"\b{rate}\s*%[^\d.!?;]{{0,55}}?\b(?:{label})\b", evidence):
            return ""
    if not income:
        return "Sổ chưa ghi nhận thu nhập trong kỳ. Bạn muốn dùng mức thu nhập nào để tính phần phân bổ?"
    needs, wants = income * 50 // 100, income * 30 // 100
    return (
        f"Áp dụng tỷ lệ trong nguồn vào thu nhập đã ghi nhận {money(income)}, mức tham khảo là "
        f"{money(needs)} cho nhu cầu thiết yếu, {money(wants)} cho mong muốn và "
        f"{money(income - needs - wants)} cho tiết kiệm."
    )
