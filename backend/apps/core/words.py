"""Amounts in words for printed documents (vouchers, cheques, invoices).

Uses the international system (thousand, million, billion), as Sri Lankan banks and
businesses do: 1,250,000.50 -> "Rupees One Million Two Hundred Fifty Thousand and Cents
Fifty Only".
"""

from decimal import ROUND_HALF_UP, Decimal

ONES = (
    "Zero One Two Three Four Five Six Seven Eight Nine Ten Eleven Twelve Thirteen Fourteen "
    "Fifteen Sixteen Seventeen Eighteen Nineteen"
).split()
TENS = "_ _ Twenty Thirty Forty Fifty Sixty Seventy Eighty Ninety".split()
SCALES = ((10**12, "Trillion"), (10**9, "Billion"), (10**6, "Million"), (10**3, "Thousand"))


def _below_thousand(n: int) -> list[str]:
    words = []
    if n >= 100:
        words += [ONES[n // 100], "Hundred"]
        n %= 100
    if n >= 20:
        words.append(TENS[n // 10] + (f"-{ONES[n % 10]}" if n % 10 else ""))
    elif n:
        words.append(ONES[n])
    return words


def number_in_words(n: int) -> str:
    if n < 0:
        raise ValueError("Negative numbers are not written in words here.")
    if n == 0:
        return "Zero"
    words = []
    for size, name in SCALES:
        if n >= size:
            words += [*_number_words(n // size), name]
            n %= size
    words += _below_thousand(n)
    return " ".join(words)


def _number_words(n: int) -> list[str]:
    return number_in_words(n).split()


def amount_in_words(amount: Decimal, currency: str = "LKR") -> str:
    """The amount to the cent, e.g. "Rupees One Thousand and Cents Five Only"."""
    if isinstance(amount, float):
        raise TypeError("Use Decimal for money.")
    value = Decimal(amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if value < 0:
        raise ValueError("Negative amounts are not written in words here.")
    whole = int(value)
    cents = int((value - whole) * 100)
    unit, small = ("Rupees", "Cents") if currency == "LKR" else (currency, "Cents")
    text = f"{unit} {number_in_words(whole)}"
    if cents:
        text += f" and {small} {number_in_words(cents)}"
    return text + " Only"
