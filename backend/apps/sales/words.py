"""Amounts in words for printed invoices (spec 6.1: "total amount in words"), in the
international system: 139,487.43 -> "Rupees One Hundred Thirty Nine Thousand Four Hundred
Eighty Seven and Cents Forty Three Only"."""

from decimal import ROUND_HALF_UP, Decimal

ONES = (
    "Zero One Two Three Four Five Six Seven Eight Nine Ten Eleven Twelve Thirteen Fourteen "
    "Fifteen Sixteen Seventeen Eighteen Nineteen"
).split()
TENS = "_ _ Twenty Thirty Forty Fifty Sixty Seventy Eighty Ninety".split()
SCALES = ((10**12, "Trillion"), (10**9, "Billion"), (10**6, "Million"), (1000, "Thousand"))


def _below_thousand(n: int) -> list[str]:
    words = []
    if n >= 100:
        words += [ONES[n // 100], "Hundred"]
        n %= 100
    if n >= 20:
        words.append(TENS[n // 10])
        n %= 10
    if n:
        words.append(ONES[n])
    return words


def number(n: int) -> str:
    """A whole number in words, e.g. 1205 -> "One Thousand Two Hundred Five"."""
    if n == 0:
        return "Zero"
    words = []
    for size, name in SCALES:
        if n >= size:
            words += _below_thousand(n // size) + [name]
            n %= size
    words += _below_thousand(n)
    return " ".join(words)


def amount(value: Decimal, currency: str = "LKR") -> str:
    value = Decimal(value).quantize(Decimal("0.01"), ROUND_HALF_UP)
    if value < 0:
        raise ValueError("Amounts in words are for amounts of zero or more.")
    whole = int(value)
    cents = int((value - whole) * 100)
    unit, small = ("Rupees", "Cents") if currency == "LKR" else (currency, "Cents")
    text = f"{unit} {number(whole)}"
    if cents:
        text += f" and {small} {number(cents)}"
    return f"{text} Only"
