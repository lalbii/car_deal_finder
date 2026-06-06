import re


def clean_text(text: str | None) -> str | None:
    if not text:
        return None
    return re.sub(r"\s+", " ", text).strip()

    
def extract_int(text: str | None) -> int | None:
    if not text:
        return None
    numbers = re.sub(r"[^\d]", "", text)
    return int(numbers) if numbers else None


def parse_price(price_text: str | None) -> int | None:
    return extract_int(price_text)