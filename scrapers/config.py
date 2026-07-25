import datetime
from typing import Dict, List, Optional

THEFT_TIME = datetime.datetime(2026, 7, 24, 20, 0, 0,
                               tzinfo=datetime.timezone(datetime.timedelta(hours=2)))

STOLEN_MODELS: Dict[str, List[str]] = {
    "FS 55":  ["fs 55", "fs55", "fs-55"],
    "FS 310": ["fs 310", "fs310", "fs-310", "fs310r"],
    "BG 86":  ["bg 86", "bg86", "bg-86"],
    "HS 81R": ["hs 81", "hs81", "hs-81", "hs81r"],
}

SEARCH_QUERIES = [
    "stihl fs 55",
    "stihl fs55",
    "stihl fs 310",
    "stihl fs310",
    "stihl debroussailleuse",
    "debroussailleuse thermique stihl",
    "stihl bg 86",
    "stihl bg86",
    "souffleur stihl",
    "souffleur a feuilles stihl",
    "stihl hs 81",
    "stihl hs81r",
    "stihl taille haie",
]


def match_model(title: Optional[str]) -> Optional[str]:
    if not title:
        return None
    t = title.lower()
    for model, keywords in STOLEN_MODELS.items():
        if any(kw in t for kw in keywords):
            return model
    return None
