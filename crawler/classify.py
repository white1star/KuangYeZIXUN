def _match(text: str, keyword: str) -> bool:
    if "+" in keyword:
        parts = [p for p in keyword.split("+") if p]
        return bool(parts) and all(p in text for p in parts)
    return keyword in text


def detect_keywords(text: str, mapping: dict) -> list:
    hits = []
    for key, words in mapping.items():
        if any(_match(text, w) for w in words):
            hits.append(key)
    return hits


def classify(title: str, summary: str, source_board: str, tags: dict) -> dict:
    text = f"{title} {summary or ''}"
    regions_map = {r: [r] for r in tags.get("regions", [])}
    return {
        "board": source_board,
        "minerals": detect_keywords(text, tags.get("minerals", {})),
        "regions": detect_keywords(text, regions_map),
        "types": detect_keywords(text, tags.get("types", {})),
    }
