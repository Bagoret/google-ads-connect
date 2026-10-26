"""Google Ads customer IDs as people type them: 123-456-7890, "123 456 7890", customers/1234567890."""
from __future__ import annotations

import re


def parse_customer_id(text) -> str | None:
    """The 10-digit ID, or None if the text is not a customer ID."""
    digits = re.sub(r"[\s-]", "", str(text or "")).removeprefix("customers/")
    return digits if re.fullmatch(r"\d{10}", digits) else None
