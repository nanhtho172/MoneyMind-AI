def money(amount: int) -> str:
    return f"{amount:,}".replace(",", ".") + " ₫"
