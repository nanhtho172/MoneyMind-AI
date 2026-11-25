import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from backend.app.core.calendar import month_dates

RELATIVE_DAYS = {
    "hom nay": 0, "ngay nay": 0, "hom qua": -1, "ngay hom qua": -1,
    "hom kia": -2, "ngay hom kia": -2, "ngay kia": 2, "ngay mai": 1,
    "sang nay": 0, "trua nay": 0, "chieu nay": 0, "toi nay": 0,
    "sang qua": -1, "trua qua": -1, "chieu qua": -1, "toi qua": -1,
    "sang mai": 1, "trua mai": 1, "chieu mai": 1, "toi mai": 1,
}
RELATIVE_MONTHS = {
    "thang nay": 0, "thang hien tai": 0, "thang truoc": -1, "thang vua roi": -1,
    "thang roi": -1, "thang sau": 1, "thang toi": 1, "thang ke tiep": 1,
}
DAY_WORDS = r"(?:ngay\s+)?(?P<word_day>\d{1,2})\s+thang\s+(?P<word_month>\d{1,2})(?:\s+nam\s+(?P<word_year>\d{2,4}))?"
DAY_NUMBERS = (
    r"(?:ngay\s+)?(?P<day>\d{1,2})\s*(?P<separator>[/\-])\s*(?P<month>\d{1,2})"
    r"(?:\s*(?P=separator)\s*(?P<year>\d{2,4}))?"
)
RELATIVE = "|".join(sorted((*RELATIVE_DAYS, *RELATIVE_MONTHS), key=len, reverse=True))
CALENDAR_LITERAL = re.compile(
    rf"\b(?:{DAY_WORDS}|(?:ngay\s+)?(?P<iso>\d{{4}}-\d{{1,2}}-\d{{1,2}})|{DAY_NUMBERS}|"
    rf"(?P<relative>{RELATIVE})|thang\s+(?P<period_month>\d{{1,2}})"
    r"(?:(?:\s+nam\s+|/)\s*(?P<period_year>\d{2,4}))?|(?:ngay|nam)\s+\d{1,4})\b"
)
WEEKDAYS = ("thứ Hai", "thứ Ba", "thứ Tư", "thứ Năm", "thứ Sáu", "thứ Bảy", "Chủ nhật")


@dataclass(frozen=True)
class CalendarMention:
    start: date | None
    end: date | None
    kind: str


def calendar_mentions(normalized: str, today: date, *, read_period: bool = False) -> list[CalendarMention]:
    return [_resolve(match, today, read_period) for match in CALENDAR_LITERAL.finditer(normalized)]


def _resolve(match: re.Match, today: date, read_period: bool) -> CalendarMention:
    relative = match["relative"]
    try:
        if relative in RELATIVE_DAYS:
            day = today + timedelta(days=RELATIVE_DAYS[relative])
            return CalendarMention(day, day, "day")
        if relative in RELATIVE_MONTHS:
            index = (today.year - 1) * 12 + today.month - 1 + RELATIVE_MONTHS[relative]
            return CalendarMention(*month_dates(index // 12 + 1, index % 12 + 1), "month")
        if month := match["period_month"]:
            year = match["period_year"] or str(today.year)
            if len(year) == 4:
                return CalendarMention(*month_dates(int(year), int(month)), "month")
        if iso := match["iso"]:
            day = date(*(int(part) for part in iso.split("-")))
            return CalendarMention(day, day, "day")
        day = match["word_day"] or match["day"]
        month = match["word_month"] or match["month"]
        year = match["word_year"] or match["year"]
        if read_period and day and month and year is None:
            year = str(today.year)
        if day and month and year and len(year) == 4:
            parsed = date(int(year), int(month), int(day))
            return CalendarMention(parsed, parsed, "day")
    except (ValueError, OverflowError):
        pass
    return CalendarMention(None, None, "invalid")


def date_time_reply(normalized: str, now: datetime) -> str | None:
    normalized = re.sub(r"^mai\b", "ngay mai", normalized)
    mentions = calendar_mentions(normalized, now.date())
    if len(mentions) > 1 or any(mention.start is None for mention in mentions):
        return None
    if re.search(r"\b(?:may gio|bao nhieu gio|gio hien tai|gio roi)\b", normalized):
        if mentions and mentions[0].start != now.date():
            return None
        return f"Bây giờ là {now:%H:%M} theo giờ Việt Nam."
    if mentions and mentions[0].kind == "month":
        first, last = mentions[0].start, mentions[0].end
        if "bao nhieu ngay" in normalized:
            return f"Tháng {first.month}/{first.year} có {last.day} ngày."
        return f"Đó là tháng {first.month}/{first.year}, từ {first:%d/%m/%Y} đến {last:%d/%m/%Y}."
    day = mentions[0].start if mentions else now.date()
    label = "Hôm nay là" if day == now.date() else "Ngày đó là"
    return f"{label} {WEEKDAYS[day.weekday()]}, ngày {day:%d/%m/%Y}."
