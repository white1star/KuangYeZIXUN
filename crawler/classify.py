def detect_keywords(text: str, mapping: dict) -> list:
    hits = []
    for key, words in mapping.items():
        if any(w in text for w in words):
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
