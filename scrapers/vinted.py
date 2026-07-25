import datetime
import http.cookiejar
import json
import random
import time
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlencode

from loguru import logger as log

BASE_URL = "https://www.vinted.be"
SEARCH_API = f"{BASE_URL}/api/v2/catalog/items"

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

CACHE_FILE = Path(__file__).parent.parent / "results" / "seen_ids_vinted.json"

MAX_RETRIES = 3
MIN_QUERY_DELAY = 3.0
MAX_QUERY_DELAY = 7.0
RESULTS_PER_QUERY = 60

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-BE,fr;q=0.9",
}


def _load_seen_ids() -> set:
    if CACHE_FILE.exists():
        try:
            return set(json.loads(CACHE_FILE.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            return set()
    return set()


def _save_seen_ids(ids: set) -> None:
    CACHE_FILE.parent.mkdir(exist_ok=True)
    CACHE_FILE.write_text(json.dumps(sorted(ids)), encoding="utf-8")


def _new_opener():
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def _prime_session(opener) -> None:
    """Visite la page d'accueil pour obtenir un jeton de session anonyme (cookies),
    requis par l'API interne du catalogue."""
    req = urllib.request.Request(f"{BASE_URL}/", headers=_HEADERS)
    opener.open(req, timeout=20).read()


def _fetch_search_items(opener, query: str) -> Optional[List[Dict]]:
    params = urlencode({"search_text": query, "per_page": RESULTS_PER_QUERY, "order": "newest_first"})
    url = f"{SEARCH_API}?{params}"
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={**_HEADERS, "Accept": "application/json"})
            with opener.open(req, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data.get("items", [])
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                log.warning("session Vinted expirée, renouvellement...")
                _prime_session(opener)
            else:
                log.warning(f"erreur ({attempt}/{MAX_RETRIES}) sur '{query}': {exc}")
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            log.warning(f"erreur ({attempt}/{MAX_RETRIES}) sur '{query}': {exc}")
        time.sleep(2 * attempt)
    log.error(f"abandon après {MAX_RETRIES} tentatives : {query}")
    return None


def _format_price(price_info: Optional[Dict]) -> str:
    if not price_info or "amount" not in price_info:
        return "N/A"
    try:
        amount = float(price_info["amount"])
    except (TypeError, ValueError):
        return "N/A"
    formatted = f"{amount:,.2f}".replace(",", " ").replace(".", ",")
    currency = price_info.get("currency_code", "")
    symbol = "€" if currency == "EUR" else f" {currency}"
    return f"{formatted} {symbol}"


def parse_item(raw: Dict) -> Dict:
    photo = raw.get("photo") or {}
    high_res = photo.get("high_resolution") or {}
    ts = high_res.get("timestamp")
    # Le timestamp de la photo (à la seconde près) sert de proxy fiable pour la date de
    # publication de l'annonce : contrairement à 2ememain.be, pas besoin de vérification
    # supplémentaire, Vinted donne directement une heure précise.
    posted_at = datetime.datetime.fromtimestamp(ts, tz=THEFT_TIME.tzinfo) if ts else None

    seller = raw.get("user") or {}

    parsed = {
        "id": raw.get("id"),
        "title": raw.get("title"),
        "price": _format_price(raw.get("price")),
        "condition": raw.get("status"),
        "posted_at": posted_at.isoformat() if posted_at else None,
        "url": raw.get("url"),
    }
    if seller.get("id") is not None:
        parsed["seller"] = {"name": seller.get("login"), "id": str(seller["id"])}
    if photo.get("url"):
        parsed["image_url"] = photo["url"]

    return parsed


def _is_posted_after_theft(posted_at: Optional[str]) -> bool:
    if not posted_at:
        return False
    try:
        dt = datetime.datetime.fromisoformat(posted_at)
    except ValueError:
        return False
    return dt >= THEFT_TIME


def _match_model(title: Optional[str]) -> Optional[str]:
    if not title:
        return None
    t = title.lower()
    for model, keywords in STOLEN_MODELS.items():
        if any(kw in t for kw in keywords):
            return model
    return None


def scrape_stolen_stihl_tools() -> List[Dict]:
    log.info("Recherche des outils Stihl volés — Vinted (Belgique)")

    previously_seen = _load_seen_ids()
    all_listings: List[Dict] = []
    seen_ids: set = set()

    opener = _new_opener()
    _prime_session(opener)

    for i, query in enumerate(SEARCH_QUERIES):
        log.info(f"scraping: {query}")
        raw_items = _fetch_search_items(opener, query)
        if raw_items is None:
            continue

        listings = [parse_item(it) for it in raw_items]
        log.success(f"scraped {len(listings)} listings for '{query}'")

        for listing in listings:
            lid = listing.get("id")
            if lid and lid not in seen_ids:
                seen_ids.add(lid)
                all_listings.append(listing)

        if i < len(SEARCH_QUERIES) - 1:
            time.sleep(random.uniform(MIN_QUERY_DELAY, MAX_QUERY_DELAY))

    recent = [l for l in all_listings if _is_posted_after_theft(l.get("posted_at"))]
    log.info(f"{len(all_listings)} annonces collectées → {len(recent)} postées après le vol")

    matched: List[Dict] = []
    for listing in recent:
        model = _match_model(listing.get("title"))
        if model:
            listing["_matched_model"] = model
            listing["is_new"] = listing.get("id") not in previously_seen
            matched.append(listing)

    seller_listings: Dict[str, List[Dict]] = defaultdict(list)
    for listing in matched:
        sid = (listing.get("seller") or {}).get("id")
        if sid:
            seller_listings[sid].append(listing)

    for sid, items in seller_listings.items():
        models_found = {l["_matched_model"] for l in items}
        seller_name = (items[0].get("seller") or {}).get("name", "inconnu")
        if len(models_found) >= 2 or len(items) >= 2:
            print("\n" + "=" * 60)
            print("!!! ALERTE VENDEUR SUSPECT !!!")
            print(f"    Vendeur : {seller_name} (id: {sid})")
            print(f"    Modèles détectés : {', '.join(sorted(models_found))}")
            print(f"    Nombre d'annonces : {len(items)}")
            for l in items:
                tag = " [NOUVEAU]" if l.get("is_new") else ""
                print(f"    → {l.get('title')}  |  {l.get('price')}{tag}")
                if l.get("url"):
                    print(f"      {l['url']}")
            print("=" * 60 + "\n")

    matched_ids = {l.get("id") for l in matched}
    unmatched_recent = [l for l in recent if l.get("id") not in matched_ids]

    if matched:
        log.success(f"{len(matched)} annonce(s) avec modèle identifié :")
        for l in matched:
            url = l.get("url") or "URL indisponible"
            tag = " [NOUVEAU]" if l.get("is_new") else ""
            print(f"  [{l['_matched_model']}] {l.get('title')}  |  {l.get('price')}  →  {url}{tag}")

    if unmatched_recent:
        log.warning(f"{len(unmatched_recent)} annonce(s) récente(s) sans modèle identifié — à vérifier manuellement :")
        for l in unmatched_recent:
            url = l.get("url") or "URL indisponible"
            print(f"  [?] {l.get('title')}  |  {l.get('price')}  →  {url}")

    if not matched and not unmatched_recent:
        log.info("Aucune annonce postée après le vol.")

    _save_seen_ids(previously_seen | seen_ids)

    return matched
