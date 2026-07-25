import datetime
import json
import random
import re
import time
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import quote

from loguru import logger as log

from .config import THEFT_TIME, SEARCH_QUERIES, match_model

BASE_URL = "https://www.2ememain.be"

THEFT_DATE = THEFT_TIME.date()

CACHE_FILE = Path(__file__).parent.parent / "results" / "seen_ids_2ememain.json"

MAX_RETRIES = 3
MIN_QUERY_DELAY = 3.0
MAX_QUERY_DELAY = 7.0
MIN_DETAIL_DELAY = 1.0
MAX_DETAIL_DELAY = 2.5

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-BE,fr;q=0.9",
}

_MONTH_PREFIXES = [
    ("janv", 1), ("févr", 2), ("fevr", 2), ("mars", 3), ("avr", 4), ("mai", 5), ("juin", 6),
    ("juil", 7), ("août", 8), ("aout", 8), ("sept", 9), ("oct", 10), ("nov", 11), ("déc", 12), ("dec", 12),
]

_DEPUIS_RE = re.compile(
    r"[Dd]epuis\s*(\d{1,2})\s+([^\s.&']+)\.?\s*(?:&#x27;|')(\d{2}),\s*(\d{2}):(\d{2})"
)


def _month_from_label(label: str) -> Optional[int]:
    s = label.strip().lower()
    for prefix, num in _MONTH_PREFIXES:
        if s.startswith(prefix):
            return num
    return None

_PRICE_TYPE_LABELS = {
    "SEE_DESCRIPTION": "Voir description",
    "FREE": "Gratuit",
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


def _search_url(query: str) -> str:
    return f"{BASE_URL}/q/{quote(query)}/"


def _full_url(vip_url: str) -> str:
    return f"{BASE_URL}{vip_url}"


def _fetch_page(url: str) -> str:
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _fetch_page_with_retries(url: str) -> Optional[str]:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return _fetch_page(url)
        except (urllib.error.URLError, TimeoutError) as exc:
            log.warning(f"erreur ({attempt}/{MAX_RETRIES}) sur {url}: {exc}")
        except Exception as exc:
            log.warning(f"erreur ({attempt}/{MAX_RETRIES}) sur {url}: {exc}")
        time.sleep(2 * attempt)
    log.error(f"abandon après {MAX_RETRIES} tentatives : {url}")
    return None


def _parse_relative_date(date_str: Optional[str], today: datetime.date) -> Optional[datetime.date]:
    if not date_str:
        return None
    s = date_str.strip().lower()
    if s == "aujourd'hui":
        return today
    if s == "hier":
        return today - datetime.timedelta(days=1)
    if s == "avant-hier":
        return today - datetime.timedelta(days=2)
    m = re.match(r"(\d{1,2})\s+([a-zéû.]+)\s+(\d{2})$", s)
    if not m:
        return None
    day, month_label, year_short = m.groups()
    month = _month_from_label(month_label)
    if not month:
        return None
    try:
        return datetime.date(2000 + int(year_short), month, int(day))
    except ValueError:
        return None


def _fetch_precise_posted_at(vip_url: str) -> Optional[datetime.datetime]:
    html = _fetch_page_with_retries(_full_url(vip_url))
    if not html:
        return None
    m = _DEPUIS_RE.search(html)
    if not m:
        return None
    day, month_label, year_short, hour, minute = m.groups()
    month = _month_from_label(month_label)
    if not month:
        return None
    try:
        return datetime.datetime(
            2000 + int(year_short), month, int(day), int(hour), int(minute),
            tzinfo=THEFT_TIME.tzinfo,
        )
    except ValueError:
        return None


def _format_price(price_info: Optional[Dict]) -> str:
    if not price_info:
        return "N/A"
    price_type = price_info.get("priceType")
    if price_type in _PRICE_TYPE_LABELS:
        return _PRICE_TYPE_LABELS[price_type]
    cents = price_info.get("priceCents")
    if cents is None:
        return "N/A"
    formatted = f"{cents / 100:,.2f}".replace(",", " ").replace(".", ",")
    suffix = " (offre min.)" if price_type == "MIN_BID" else " (enchère)" if price_type == "FAST_BID" else ""
    return f"{formatted} €{suffix}"


def parse_search_listings(html: str) -> List[Dict]:
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if not m:
        log.warning("__NEXT_DATA__ introuvable dans la page")
        return []
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        log.warning("JSON __NEXT_DATA__ invalide")
        return []

    try:
        raw_listings = data["props"]["pageProps"]["searchRequestAndResponse"]["listings"]
    except (KeyError, TypeError):
        return []

    today = datetime.datetime.now().date()
    parsed_listings = []
    for listing in raw_listings:
        location = listing.get("location") or {}
        seller = listing.get("sellerInformation") or {}
        pictures = listing.get("pictures") or []
        image_url = pictures[0].get("url") if pictures else None
        if not image_url:
            image_urls = listing.get("imageUrls") or []
            image_url = ("https:" + image_urls[0]) if image_urls else None

        posted_date = _parse_relative_date(listing.get("date"), today)

        parsed_listing = {
            "id": listing.get("itemId"),
            "title": listing.get("title"),
            "price": _format_price(listing.get("priceInfo")),
            "location": location.get("cityName", ""),
            "is_sold": False,
            "is_pending": bool(listing.get("reserved", False)),
            "creation_date": posted_date.isoformat() if posted_date else None,
            "_vip_url": listing.get("vipUrl"),
        }

        if seller.get("sellerId") is not None:
            parsed_listing["seller"] = {"name": seller.get("sellerName"), "id": str(seller.get("sellerId"))}
        if image_url:
            parsed_listing["image_url"] = image_url

        parsed_listings.append(parsed_listing)

    log.success(f"parsed {len(parsed_listings)} listings from the page")
    return parsed_listings


def _is_posted_after_theft(creation_date: Optional[str]) -> bool:
    if not creation_date:
        return False
    try:
        d = datetime.date.fromisoformat(creation_date)
    except ValueError:
        return False
    return d >= THEFT_DATE




def scrape_stolen_stihl_tools() -> List[Dict]:
    log.info("Recherche des outils Stihl volés — 2ememain.be (Belgique)")

    previously_seen = _load_seen_ids()
    all_listings: List[Dict] = []
    seen_ids: set = set()

    for i, query in enumerate(SEARCH_QUERIES):
        url = _search_url(query)
        log.info(f"scraping: {query}")
        html = _fetch_page_with_retries(url)
        if html is None:
            continue

        listings = parse_search_listings(html)
        log.success(f"scraped {len(listings)} listings for '{query}'")

        for listing in listings:
            lid = listing.get("id")
            if lid and lid not in seen_ids:
                seen_ids.add(lid)
                all_listings.append(listing)

        if i < len(SEARCH_QUERIES) - 1:
            time.sleep(random.uniform(MIN_QUERY_DELAY, MAX_QUERY_DELAY))

    recent = [l for l in all_listings if _is_posted_after_theft(l.get("creation_date"))]
    log.info(f"{len(all_listings)} annonces collectées → {len(recent)} avec une date affichée après le vol")

    matched: List[Dict] = []
    for listing in recent:
        model = match_model(listing.get("title"))
        if not model:
            continue
        listing["_matched_model"] = model

        vip_url = listing.get("_vip_url")
        precise_posted_at = _fetch_precise_posted_at(vip_url) if vip_url else None
        time.sleep(random.uniform(MIN_DETAIL_DELAY, MAX_DETAIL_DELAY))

        if precise_posted_at is not None:
            listing["posted_at"] = precise_posted_at.isoformat()
            if precise_posted_at < THEFT_TIME:
                log.info(
                    f"'{listing.get('title')}' écarté : posté le "
                    f"{precise_posted_at.strftime('%d/%m %H:%M')}, avant le vol "
                    f"(date de recherche trompeuse, probablement une annonce remise en avant)"
                )
                continue
        else:
            log.warning(f"heure précise indisponible pour '{listing.get('title')}' — annonce conservée par prudence")

        if vip_url:
            listing["url"] = _full_url(vip_url)
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
            print("ALARM: !!! ALERTE VENDEUR SUSPECT !!!")
            print(f"ALARM:     Vendeur : {seller_name} (id: {sid})")
            print(f"ALARM:     Modèles détectés : {', '.join(sorted(models_found))}")
            print(f"ALARM:     Nombre d'annonces : {len(items)}")
            for l in items:
                tag = " [NOUVEAU]" if l.get("is_new") else ""
                print(f"ALARM:     → {l.get('title')}  |  {l.get('price')}{tag}")
                if l.get("url"):
                    print(f"ALARM:       {l['url']}")
            print("=" * 60 + "\n")

    matched_ids = {l.get("id") for l in matched}
    unmatched_recent = [l for l in recent if l.get("id") not in matched_ids]

    if matched:
        log.success(f"{len(matched)} annonce(s) avec modèle identifié :")
        for l in matched:
            url = l.get("url") or "URL indisponible"
            tag = " [NOUVEAU]" if l.get("is_new") else ""
            print(f"ALARM:   [{l['_matched_model']}] {l.get('title')}  |  {l.get('price')}  →  {url}{tag}")

    if unmatched_recent:
        log.warning(
            f"{len(unmatched_recent)} annonce(s) récente(s) sans modèle identifié — à vérifier manuellement "
            f"(date approximative, non vérifiée à l'heure près) :"
        )
        for l in unmatched_recent:
            vip_url = l.get("_vip_url")
            url = _full_url(vip_url) if vip_url else "URL indisponible"
            print(f"  [?] {l.get('title')}  |  {l.get('price')}  →  {url}")

    if not matched and not unmatched_recent:
        log.info("Aucune annonce postée après le vol.")

    _save_seen_ids(previously_seen | seen_ids)

    return matched
