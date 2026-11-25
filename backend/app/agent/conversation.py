import re
from backend.app.agent.dates import CALENDAR_LITERAL
from backend.app.schemas.chat import Intent

GREETING = re.compile(
    r"(?:xin chao|chao buoi (?:sang|trua|chieu|toi)|chao|hello|hi|hey)"
    r"(?: (?:ban|moneymind|tro ly|nhe|a|nha|ban oi))*[!.?]*"
)
HELP = re.compile(
    r"\b(?:moneymind|ban|ung dung(?: nay)?)\b.{0,50}\b"
    r"(?:lam duoc gi|co the lam gi|co the giup gi|giup (?:toi|minh) (?:duoc )?gi|"
    r"giup (?:toi|minh) lam gi|co (?:nhung )?(?:tinh nang|chuc nang) gi)(?: cho (?:toi|minh))?[?!. ]*$"
)
CLOCK_QUESTION = re.compile(
    r"\b(?:ngay (?:bao nhieu|may|gi|nao|hien tai)|bao nhieu tay|thu (?:may|gi)|"
    r"(?:may gio|bao nhieu gio)(?: roi| bay gio| hien tai)|gio hien tai|gio roi|thang (?:bao nhieu|may)|"
    r"thang (?:nay|truoc|sau|roi|vua roi) co bao nhieu ngay)\b"
    r"|(?:^|\b(?:bay gio|hien tai|luc nay) )(?:la )?(?:may gio|bao nhieu gio)[?!. ]*$"
)
CURRENT_CLOCK = re.compile(r"\b(?:bay gio|hien tai|luc nay|gio roi|thu (?:may|gi) roi)\b|^mai\b")
CLOCK_ONLY = re.compile(r"(?:ngay (?:bao nhieu|may|gi|nao)|bao nhieu tay|thu (?:may|gi)|may gio|bao nhieu gio)")
ACCOUNT_READ = re.compile(
    r"\b(?:tong (?:thu|chi)(?: tieu)?|so du|dong tien rong|"
    r"(?:da |vua )?(?:tieu|chi|thu|kiem duoc|nhan duoc) (?:het )?(?:bao nhieu|may dong)|"
    r"(?:toi|minh|em) (?:da|vua) (?:chi|tieu|mua|thu|nhan) (?:gi|(?:nhung |cac )?(?:khoan )?(?:gi|nao))|"
    r"(?:ngan sach|han muc)\b[^?.!]{0,55}\b(?:con bao nhieu|con lai|da chi|con du|cua (?:toi|minh))|"
    r"(?:xem|liet ke|tim|tra cuu|thong ke) (?:tat ca |cac |nhung )?"
    r"(?:giao dich|lich su (?:thu chi|mua sam|giao dich)|khoan (?:thu|chi)|thu chi|ngan sach|han muc)|"
    r"(?:giao dich|khoan (?:thu|chi)) (?:gan nhat|moi nhat|cua (?:toi|minh))|"
    r"(?:chi tieu|thu nhap|lich su thu chi) cua (?:toi|minh|em)|"
    r"tai khoan cua (?:toi|minh|em) (?:con|co|da)|"
    r"bao nhieu (?:giao dich|khoan (?:thu|chi))|bao nhieu tien (?:da chi|da tieu|con))\b"
)
EDUCATIONAL = re.compile(r"\b(?:la gi|nghia la gi|dinh nghia|khai niem|duoc tinh nhu the nao|cach tinh)\b")
SPENDING = re.compile(r"\b(?:chi tieu|khoan chi|da chi|da tieu)\b")
ALLOCATION_RULE = re.compile(r"(?<!\d)50[\s/–—-]+30[\s/–—-]+20(?!\d)")
PERSON = re.compile(r"\b(?:toi|minh|em)\b")
APPLICATION = re.compile(r"\b(?:ap dung|van dung|truong hop cua (?:toi|minh|em)|"
                         r"(?:rieng|doi voi|voi|cho) (?:toi|minh|em|ban than))\b")
REFERENCE = re.compile(r"\b(?:cach|quy tac|nguyen tac|goi y|phuong phap|so lieu) (?:nay|do|tren|vua neu)\b")
ADVISORY_DOMAINS = {"FINANCIAL_ADVICE", "PERSONAL_FINANCIAL_ADVICE"}
ADVICE_REQUEST = re.compile(r"\b(?:nen|tu van|loi khuyen|cai thien|goi y|lam sao|lam the nao)\b")
TIED_TO_SPENDING = re.compile(r"\b(?:dua (?:tren|vao)|can cu|voi|xet theo)\b")
OWN_ACCOUNT = re.compile(r"\b(?:cua (?:toi|minh|em)|(?:toi|minh|em) (?:da|vua))\b")
HYPOTHETICAL = re.compile(r"\b(?:vi du|gia su|neu|chang han|minh hoa|mo phong)\b")
WRITE = re.compile(r"\b(?:ghi|luu|them|tao)\s+(?:lai\s+)?(?:(?:mot|khoan|giao dich)\s+)?"
                   r"(?:giao dich|khoan thu|khoan chi|thu|chi)\b|"
                   r"\b(?:dat|tao|lap|dieu chinh|cap nhat) (?:ngan sach|han muc)\b")
TRANSACTION_STATEMENT = re.compile(
    r"\b(?:toi|minh|em) (?:da |vua )?(?:chi|tieu|tra|nhan|thu)\s+\d[\d.,]*"
    r"\s*(?:k|d|vnd|dong|nghin|ngan|trieu|tr\d{0,2})\b"
)
FOLLOW_UP = re.compile(
    r"^(?:the\s+)?(?:con|vay|the thi|the|tai sao|vi sao|nhu vay|no|cai do|dieu do|cho (?:toi|minh) vi du|"
    r"vi du (?:di|cu the)|giai thich them|noi ro hon)\b|\b(?:thi sao|vua noi)\b"
)
DECISION_TEXT = re.compile(
    r"(?:ok|oke|dong y|xac nhan|chap nhan|huy|khong dong y|luu di|ghi di|lam di)"
    r"(?: (?:di|nhe|nha|a|giao dich|ban nhap|ngan sach))*[!.?]*"
)


def previous_domain(history: list[dict], intent: Intent) -> list[dict]:
    turns = []
    for item in reversed(history):
        if item["intent"] != intent or not item["user"]:
            break
        turns.append(item)
    return list(reversed(turns))


def is_follow_up(normalized: str) -> bool:
    return len(normalized) <= 180 and FOLLOW_UP.search(normalized) is not None


def time_follow_up(normalized: str) -> bool:
    period = re.sub(r"^(?:the )?(?:con|vay|the) ", "", normalized.strip(" .?!"))
    period = re.sub(r" (?:thi sao|nhe|a)$", "", period)
    return CALENDAR_LITERAL.fullmatch(period) is not None


def asks_backend_clock(normalized: str) -> bool:
    return CLOCK_QUESTION.search(normalized) is not None and (
        CALENDAR_LITERAL.search(normalized) is not None
        or CURRENT_CLOCK.search(normalized) is not None
        or CLOCK_ONLY.fullmatch(normalized.strip(" .!?")) is not None
    )


def local_intent(normalized: str, history: list[dict]) -> Intent | None:
    if GREETING.fullmatch(normalized):
        return "GREETING"
    if DECISION_TEXT.fullmatch(normalized) and any(
        turn["status"] == "PENDING_CONFIRMATION" and turn["intent"] == "SET_BUDGET" for turn in history
    ):
        return "CLARIFICATION"
    if WRITE.search(normalized) and allows_new_write(normalized) and "bao nhieu" not in normalized:
        return "SET_BUDGET" if re.search(r"\b(?:ngan sach|han muc)\b", normalized) else "CREATE_TRANSACTION"
    if (SPENDING.search(normalized) and ADVICE_REQUEST.search(normalized)
            and not HYPOTHETICAL.search(normalized)
            and (PERSON.search(normalized) or TIED_TO_SPENDING.search(normalized) and CALENDAR_LITERAL.search(normalized))):
        return "PERSONAL_FINANCIAL_ADVICE"
    applying = re.search(r"\b(?:ap dung|van dung|doi chieu)\b", normalized)
    explaining = EDUCATIONAL.search(normalized) or re.search(r"\b(?:giai thich|gioi thieu|cho (?:toi|minh) biet)\b", normalized)
    if (ALLOCATION_RULE.search(normalized) and PERSON.search(normalized) and APPLICATION.search(normalized)
            and (applying or not explaining)):
        return "PERSONAL_FINANCIAL_ADVICE"
    if ALLOCATION_RULE.search(normalized) and explaining and PERSON.search(normalized) and not applying:
        return "FINANCIAL_ADVICE"
    if history and history[-1]["intent"] in ADVISORY_DOMAINS and not ACCOUNT_READ.search(normalized):
        if PERSON.search(normalized) and REFERENCE.search(normalized):
            return "PERSONAL_FINANCIAL_ADVICE"
        if (PERSON.search(normalized) and APPLICATION.search(normalized) and
                (is_follow_up(normalized) or re.search(r"\b(?:ap dung|van dung|truong hop|rieng)\b", normalized))):
            return "PERSONAL_FINANCIAL_ADVICE"
        if history[-1]["intent"] == "PERSONAL_FINANCIAL_ADVICE" and time_follow_up(normalized):
            return "PERSONAL_FINANCIAL_ADVICE"
    if ACCOUNT_READ.search(normalized) and (not EDUCATIONAL.search(normalized) or OWN_ACCOUNT.search(normalized)):
        return "QUERY_STATISTICS"
    if "?" not in normalized and TRANSACTION_STATEMENT.search(normalized) and allows_new_write(normalized):
        return "CREATE_TRANSACTION"
    if asks_backend_clock(normalized):
        return "DATE_TIME"
    if HELP.search(normalized):
        return "GENERAL_CONVERSATION"
    if (time_follow_up(normalized) or is_follow_up(normalized) and "ngan sach" in normalized) and previous_domain(history, "QUERY_STATISTICS"):
        return "QUERY_STATISTICS"
    return None


def allows_new_write(normalized: str) -> bool:
    if DECISION_TEXT.fullmatch(normalized) or EDUCATIONAL.search(normalized) or HYPOTHETICAL.search(normalized):
        return False
    if WRITE.search(normalized):
        return True
  
    return not is_follow_up(normalized) and not CALENDAR_LITERAL.fullmatch(normalized.strip(" .?!"))
