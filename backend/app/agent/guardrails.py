import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext

from pydantic import ValidationError

from backend.app.agent.dates import CALENDAR_LITERAL, calendar_mentions
from backend.app.agent.llm import AgentProblem
from backend.app.models.finance import TransactionType
from backend.app.schemas.chat import (
    BudgetExtraction, PendingAction, PendingBudget, PendingTransaction, TransactionDraft,
    TransactionExtraction,
)
from backend.app.schemas.finance import BudgetSet, CategoryView


def folded(text: str) -> str:
    plain = unicodedata.normalize("NFD", text.casefold().replace("đ", "d"))
    return " ".join("".join(char for char in plain if not unicodedata.combining(char)).split())


SENSITIVE = re.compile(
    r"\b(?:sk|gsk|ghp)[_-][\w-]{8,}\b|\bBearer\s+[\w.-]{8,}|"
    r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?<!\d)(?:\+84|0)(?:[ .-]?\d){9,10}\b|"
    r"\b(?:mật khẩu|password|otp|api[_ ]?key|số tài khoản|cccd)\s*[:=]\s*\S+|"
    r"\b(?:số tài khoản|cccd)\s+\d{6,19}\b",
    re.IGNORECASE,
)
ACCOUNT_OVERRIDE = re.compile(
    r"\b(?:user_id|demo_[ab]|another user|other user|nguoi khac|tai khoan khac|"
    r"tai khoan cua(?! (?:toi|minh|em|chinh toi|chinh minh)\b)|cross.account)\b"
)
INSTRUCTION_OVERRIDE = re.compile(
    r"\b(?:ignore (?:all |previous |the )*(?:instructions|rules)|system prompt|developer message|"
    r"bo qua (?:cac |moi )?(?:quy tac|huong dan|chi dan|(?:buoc )?xac nhan)|"
    r"khong can xac nhan|bypass (?:hitl|confirmation))\b"
)
PERSONAL_INVESTMENT = re.compile(
    r"\b(?:co phieu|chung khoan|bitcoin|crypto|tien ao|ma co phieu|danh muc dau tu|(?<!bat )dau tu)\b"
    r".{0,80}\b(?:nen|mua|ban|khuyen nghi|cho toi|ca nhan)\b|"
    r"\b(?:nen|hay|tu van|chon|mua|ban|khuyen nghi)\b.{0,80}"
    r"\b(?:co phieu|chung khoan|bitcoin|crypto|tien ao|danh muc dau tu|(?<!bat )dau tu)\b"
)


def sanitize(text: str) -> str:
    return SENSITIVE.sub("[đã ẩn]", unicodedata.normalize("NFKC", text))


def validate_input(text: str) -> None:
    normalized = folded(text)
    if ACCOUNT_OVERRIDE.search(normalized):
        raise AgentProblem("ACCOUNT_SCOPE", "Chỉ được truy vấn dữ liệu của tài khoản đang đăng nhập.")
    if INSTRUCTION_OVERRIDE.search(normalized):
        if "xac nhan" in normalized or "confirmation" in normalized:
            raise AgentProblem("INPUT_BLOCKED", "Để ghi giao dịch, hãy kiểm tra bản nháp rồi bấm Xác nhận.")
        raise AgentProblem("INPUT_BLOCKED", "Yêu cầu không phù hợp với quy tắc của MoneyMind.")
    if PERSONAL_INVESTMENT.search(normalized):
        raise AgentProblem("INVESTMENT_ADVICE_BLOCKED", "MoneyMind chỉ cung cấp kiến thức tài chính chung.")


WORD_DIGITS = dict(zip("khong mot hai ba bon nam sau bay tam chin".split(), range(10), strict=True))
WORD_DIGITS.update({"tu": 4, "lam": 5})
WORD_SCALES = {"ty": 10**9, "trieu": 10**6, "nghin": 10**3, "ngan": 10**3}
WORD_DIGIT = "(?:" + "|".join(WORD_DIGITS) + ")"
WORD_TENS = rf"(?:(?:{WORD_DIGIT} )?muoi(?: {WORD_DIGIT})?)"
WORD_GROUP = rf"(?:{WORD_DIGIT} tram(?: (?:{WORD_TENS}|(?:(?:linh|le) )?{WORD_DIGIT}))?|{WORD_TENS}|{WORD_DIGIT})"
WORD_AMOUNT = rf"(?:am )?(?:(?:{WORD_GROUP} (?:ty|trieu|nghin|ngan)(?: |(?=\b)))+(?:{WORD_GROUP} dong|dong)?|{WORD_GROUP} dong)"
NUMBER_AMOUNT = (
    r"(?:am\s+|[+-]\s*)?(?:\d+\s*tr\s*\d{1,2}|(?:\d{1,3}(?:[.,]\d{3})+|\d+(?:[.,]\d+)?)"
    r"(?:\s*(?:(?:nghin|ngan|trieu|ty)(?:\s+dong)?|vnd|dong|tr|k|d))?)"
)
AMOUNT_PATTERN = re.compile(rf"(?<![\w.,])(?P<amount>{NUMBER_AMOUNT}|{WORD_AMOUNT})(?![\w]|[.,]\d)")
REPEATED_ACTION = re.compile(
    r"\b(?:moi (?:bua|khoan|giao dich|lan)|lan luot|(?:hai|ba|nhieu|[2-9]) (?:khoan|giao dich))\b|"
    r"\b(?:an sang|an trua|an toi|tra|mua|nhan)\b.{0,80}"
    r"\b(?:va|roi)\s+(?:an sang|an trua|an toi|tra|mua|nhan)\b"
)


def clarify(code: str, message: str) -> AgentProblem:
    return AgentProblem(code, message, clarification=True)


def checked_amount(text: str, evidence: str | None, multiple: bool, *, correction: bool = False) -> int:
    normalized = folded(text)
    candidates = [
        match["amount"].strip()
        for match in AMOUNT_PATTERN.finditer(CALENDAR_LITERAL.sub(" ", normalized))
    ]
    if multiple or (not correction and (len(candidates) > 1 or REPEATED_ACTION.search(normalized))):
        raise clarify("MULTIPLE_ACTIONS", "Hãy tách mỗi giao dịch hoặc ngân sách thành một yêu cầu.")
    token = folded(evidence) if evidence else ""
    if token not in candidates:
        raise clarify("AMOUNT_REQUIRED", "Hãy ghi rõ một số tiền bằng VNĐ.")
    if token.startswith("am "):
        raise clarify("INVALID_AMOUNT", "Số tiền ghi sổ phải lớn hơn 0 đồng.")
    compact = token.replace(" ", "").removesuffix("dong") if re.match(r"[+-]?\s*\d", token) else token
    with localcontext() as context:
        context.prec = len(compact) + 8
        try:
            value = Decimal(parse_words(compact)) if " " in compact else _parse_amount(compact)
        except (InvalidOperation, ValueError):
            raise clarify("INVALID_AMOUNT", "Định dạng số tiền chưa rõ.") from None
    if not 0 < value <= 2**63 - 1 or value != value.to_integral_value():
        raise clarify("INVALID_AMOUNT", "Số tiền phải là số nguyên dương hợp lệ tính bằng VNĐ.")
    return int(value)


def parse_words(token: str) -> int:
    negative = token.startswith("am ")
    total = group = digit = 0
    last_scale = 10**10
    for word in token.removeprefix("am ").split():
        if word in WORD_DIGITS:
            digit = WORD_DIGITS[word]
        elif word == "tram":
            group, digit = digit * 100, 0
        elif word == "muoi":
            group, digit = group + (digit or 1) * 10, 0
        elif word in WORD_SCALES:
            scale = WORD_SCALES[word]
            if scale >= last_scale:
                raise ValueError("Invalid monetary scale")
            total, group, digit, last_scale = total + (group + digit) * scale, 0, 0, scale
    return (-1 if negative else 1) * (total + group + digit)


def _parse_amount(token: str) -> Decimal:
    if shorthand := re.fullmatch(r"([+-]?\d+)tr(\d{1,2})", token):
        return Decimal(f"{shorthand[1]}.{shorthand[2]}") * 1_000_000
    number, unit = re.fullmatch(r"([+-]?[\d.,]+)([a-z]*)", token).groups()
    multiplier = {"k": 1_000, "tr": 1_000_000, **WORD_SCALES}
    if re.fullmatch(r"[+-]?\d{1,3}(?:\.\d{3})+", number):
        number = number.replace(".", "")
    elif re.fullmatch(r"[+-]?\d{1,3}(?:,\d{3})+", number):
        number = number.replace(",", "")
    return Decimal(number.replace(",", ".")) * multiplier.get(unit, 1)


def checked_date(text: str, today: date) -> date:
    mentions = calendar_mentions(folded(text), today)
    if len(mentions) == 1 and mentions[0].kind == "day" and mentions[0].start:
        return mentions[0].start
    raise clarify("DATE_REQUIRED", "Hãy ghi rõ ngày, ví dụ hôm nay hoặc ngày/tháng/năm.")


def checked_period(text: str, today: date) -> tuple[int, int]:
    mentions = calendar_mentions(folded(text), today)
    if len(mentions) == 1 and mentions[0].kind == "month" and mentions[0].start:
        start = mentions[0].start
        return start.year, start.month
    raise clarify("PERIOD_REQUIRED", "Hãy ghi rõ tháng ngân sách, ví dụ tháng này hoặc tháng 12/2026.")


def match_category(categories: list[CategoryView], name: str | None) -> CategoryView:
    token = folded(name) if name else ""
    matches = [category for category in categories if folded(category.name) == token]
    if len(matches) != 1:
        raise clarify("CATEGORY_REQUIRED", "Hãy ghi rõ một danh mục có trong MoneyMind.")
    return matches[0]


def validate_action(
    text: str, draft: TransactionExtraction | BudgetExtraction, categories: list[CategoryView], today: date,
) -> PendingAction:
    amount = checked_amount(text, draft.amount_text, draft.multiple)
    if isinstance(draft, TransactionExtraction) and draft.type is None:
        raise clarify("TYPE_REQUIRED", "Đây là khoản thu hay khoản chi?")
    kind = TransactionType(draft.type) if isinstance(draft, TransactionExtraction) else TransactionType.EXPENSE
    category = match_category([item for item in categories if item.type == kind], draft.category)
    try:
        if isinstance(draft, TransactionExtraction):
            return PendingTransaction(
                kind="CREATE_TRANSACTION", category=category.name,
                payload=TransactionDraft(
                    type=kind, category_id=category.id, amount=amount,
                    transaction_date=checked_date(text, today),
                    note=sanitize(draft.note.strip())[:500] if draft.note else None,
                ),
            )
        year, month = checked_period(text, today)
        return PendingBudget(
            kind="SET_BUDGET", category=category.name,
            payload=BudgetSet(category_id=category.id, amount=amount, year=year, month=month),
        )
    except ValidationError:
        raise clarify("INVALID_ACTION", "Hãy kiểm tra lại dữ liệu và kỳ ngân sách.") from None
