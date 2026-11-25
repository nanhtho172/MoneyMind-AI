from calendar import monthrange
from datetime import date, datetime
from zoneinfo import ZoneInfo

LOCAL_TIME_ZONE = ZoneInfo("Asia/Ho_Chi_Minh")


def local_now() -> datetime:
    return datetime.now(LOCAL_TIME_ZONE)


def local_today() -> date:
    return local_now().date()


def month_dates(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, monthrange(year, month)[1])
