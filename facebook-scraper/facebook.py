import asyncio
import json
import random
import re
import datetime
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import quote
from loguru import logger as log
from playwright.async_api import async_playwright, BrowserContext, TimeoutError as PlaywrightTimeoutError

MARKETPLACE_LOCATION = "brussels"
SEARCH_RADIUS_KM = 200

THEFT_TIME = datetime.datetime(2026, 7, 24, 20, 0, 0,
                               tzinfo=datetime.timezone(datetime.timedelta(hours=2)))
THEFT_TIMESTAMP = int(THEFT_TIME.timestamp())

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
    "stihl débroussailleuse",
    "debroussailleuse thermique stihl",
    "stihl bg 86",
    "stihl bg86",
    "souffleur stihl",
    "souffleur a feuilles stihl",
    "stihl hs 81",
    "stihl hs81r",
    "taille haie stihl",
    "stihl taille haie",
]

CACHE_FILE = Path(__file__).parent / "results" / "seen_listing_ids.json"

MAX_RETRIES = 3
SCROLL_PASSES = 2
MIN_QUERY_DELAY = 3.0
MAX_QUERY_DELAY = 7.0

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

_COOKIE_SELECTORS = [
    "button[title='Allow all cookies']",
    "button[title='Accepter tous les cookies']",
    "button[title='Autoriser tous les cookies']",
    "div[aria-label='Allow all cookies']",
    "[data-testid='cookie-policy-manage-dialog-accept-button']",
]


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


async def _accept_cookies(context: BrowserContext) -> None:
    page = await context.new_page()
    try:
        await page.goto("https://www.facebook.com/", wait_until="domcontentloaded", timeout=20_000)
        await page.wait_for_timeout(2000)
        for selector in _COOKIE_SELECTORS:
            try:
                btn = page.locator(selector)
                if await btn.count() > 0:
                    await btn.first.click(timeout=3000)
                    await page.wait_for_timeout(1000)
                    break
            except Exception:
                continue
    finally:
        await page.close()


async def _fetch_page(context: BrowserContext, url: str) -> str:
    page = await context.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_timeout(2000)
        for _ in range(SCROLL_PASSES):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(1200)
        return await page.content()
    finally:
        await page.close()


async def _fetch_page_with_retries(context: BrowserContext, url: str) -> Optional[str]:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return await _fetch_page(context, url)
        except PlaywrightTimeoutError:
            log.warning(f"timeout ({attempt}/{MAX_RETRIES}) sur {url}")
        except Exception as exc:
            log.warning(f"erreur ({attempt}/{MAX_RETRIES}) sur {url}: {exc}")
        await asyncio.sleep(2 * attempt)
    log.error(f"abandon après {MAX_RETRIES} tentatives : {url}")
    return None


def parse_marketplace_listing(html: str) -> List[Dict]:
    def find_listings(obj, depth=0):
        if depth > 50:
            return []
        if isinstance(obj, dict):
            results = [obj] if obj.get("__typename") in ["GroupCommerceProductItem", "MarketplaceProductItem"] else []
            return results + [item for value in obj.values() for item in find_listings(value, depth + 1)]
        return [
            item for sublist in (obj if isinstance(obj, list) else []) for item in find_listings(sublist, depth + 1)
        ]

    scripts = re.findall(r'<script type="application/json"[^>]*>(.*?)</script>', html, re.DOTALL)
    all_listings = []
    for script in scripts:
        try:
            all_listings.extend(find_listings(json.loads(script)))
        except (json.JSONDecodeError, RecursionError):
            continue

    parsed_listings = []
    for listing in all_listings:
        geocode = listing.get("location", {}).get("reverse_geocode", {})
        city, state = geocode.get("city", ""), geocode.get("state", "")
        location = f"{city}, {state}" if city and state else (city or state)

        parsed_listing = {
            "id": listing.get("id"),
            "title": listing.get("marketplace_listing_title"),
            "price": (listing.get("listing_price") or {}).get("formatted_amount", "N/A"),
            "location": location,
            "is_sold": listing.get("is_sold", False),
            "is_pending": listing.get("is_pending", False),
            "creation_time": listing.get("creation_time"),
        }

        if seller_data := listing.get("marketplace_listing_seller"):
            parsed_listing["seller"] = {"name": seller_data.get("name"), "id": seller_data.get("id")}
        if image := listing.get("primary_listing_photo", {}).get("image"):
            parsed_listing["image_url"] = image.get("uri")

        parsed_listings.append(parsed_listing)

    log.success(f"parsed {len(parsed_listings)} marketplace listings from the page")
    return parsed_listings


def _is_posted_after_theft(creation_time: Optional[int]) -> bool:
    if creation_time is None:
        return False
    return creation_time >= THEFT_TIMESTAMP


def _match_model(title: Optional[str]) -> Optional[str]:
    if not title:
        return None
    t = title.lower()
    for model, keywords in STOLEN_MODELS.items():
        if any(kw in t for kw in keywords):
            return model
    return None


def _listing_url(listing_id: str) -> str:
    return f"https://www.facebook.com/marketplace/item/{listing_id}/"


def _search_url(query: str) -> str:
    return (
        f"https://www.facebook.com/marketplace/{MARKETPLACE_LOCATION}/search"
        f"?query={quote(query)}&radius={SEARCH_RADIUS_KM}&exact=false"
    )


async def scrape_stolen_stihl_tools() -> List[Dict]:
    log.info("Recherche des outils Stihl volés — Bruxelles + 200 km (Wallonie / Nord de la France)")

    previously_seen = _load_seen_ids()
    all_listings: List[Dict] = []
    seen_ids: set = set()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, channel="chrome")
        context = await browser.new_context(locale="fr-BE", user_agent=_USER_AGENT)

        await _accept_cookies(context)

        for i, query in enumerate(SEARCH_QUERIES):
            url = _search_url(query)
            log.info(f"scraping: {query}")
            html = await _fetch_page_with_retries(context, url)
            if html is None:
                continue

            listings = parse_marketplace_listing(html)
            log.success(f"scraped {len(listings)} listings for '{query}'")

            for listing in listings:
                lid = listing.get("id")
                if lid and lid not in seen_ids:
                    seen_ids.add(lid)
                    all_listings.append(listing)

            if i < len(SEARCH_QUERIES) - 1:
                await asyncio.sleep(random.uniform(MIN_QUERY_DELAY, MAX_QUERY_DELAY))

        await browser.close()

    recent = [l for l in all_listings if _is_posted_after_theft(l.get("creation_time"))]
    log.info(f"{len(all_listings)} annonces collectées → {len(recent)} postées après le vol")

    matched: List[Dict] = []
    for listing in recent:
        model = _match_model(listing.get("title"))
        if model:
            listing["_matched_model"] = model
            lid = listing.get("id")
            if lid:
                listing["url"] = _listing_url(lid)
            listing["is_new"] = lid not in previously_seen
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
                lid = l.get("id")
                tag = " [NOUVEAU]" if l.get("is_new") else ""
                print(f"    → {l.get('title')}  |  {l.get('price')}{tag}")
                if lid:
                    print(f"      {_listing_url(lid)}")
            print("=" * 60 + "\n")

    matched_ids = {l.get("id") for l in matched}
    unmatched_recent = [l for l in recent if l.get("id") not in matched_ids]

    if matched:
        log.success(f"{len(matched)} annonce(s) avec modèle identifié :")
        for l in matched:
            lid = l.get("id")
            url = _listing_url(lid) if lid else "URL indisponible"
            tag = " [NOUVEAU]" if l.get("is_new") else ""
            print(f"  [{l['_matched_model']}] {l.get('title')}  |  {l.get('price')}  →  {url}{tag}")

    if unmatched_recent:
        log.warning(f"{len(unmatched_recent)} annonce(s) récente(s) sans modèle identifié — à vérifier manuellement :")
        for l in unmatched_recent:
            lid = l.get("id")
            url = _listing_url(lid) if lid else "URL indisponible"
            print(f"  [?] {l.get('title')}  |  {l.get('price')}  →  {url}")

    if not matched and not unmatched_recent:
        log.info("Aucune annonce postée après le vol.")

    _save_seen_ids(previously_seen | seen_ids)

    return matched
