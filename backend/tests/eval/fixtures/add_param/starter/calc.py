"""A tiny calculator module used as the starter for the add_param task.

Coder must add a `tax_rate` parameter to `format_price` and update its callers,
WITHOUT touching unrelated code. This tests:
  - Following conventions (match the existing style: docstrings, type hints, 4-space indent)
  - Not reformatting unrelated lines (git diff should be small and focused)
"""


def format_price(amount: float, currency: str = "USD") -> str:
    """Format a price with currency symbol and 2 decimal places."""
    symbols = {"USD": "$", "EUR": "€", "GBP": "£"}
    symbol = symbols.get(currency, "")
    return f"{symbol}{amount:.2f}"


def receipt_line(item: str, amount: float) -> str:
    """Build a single receipt line for an item."""
    price = format_price(amount)
    return f"{item}: {price}"


def grand_total(items: list[tuple[str, float]]) -> str:
    """Sum up items and format the total."""
    total = sum(amount for _, amount in items)
    return format_price(total)


# ── demo / sanity check ───────────────────────────────────────────────────
if __name__ == "__main__":
    print(receipt_line("Coffee", 3.5))
    print(receipt_line("Bagel", 2.25))
    print(grand_total([("Coffee", 3.5), ("Bagel", 2.25)]))
