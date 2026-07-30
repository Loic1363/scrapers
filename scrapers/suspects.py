import datetime
import json
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

STORE_FILE = Path(__file__).parent.parent / "results" / "suspects.json"
GEOCODE_CACHE_FILE = Path(__file__).parent.parent / "results" / "geocode_cache.json"

BATCH_THRESHOLD = datetime.timedelta(hours=24)


def _normalize_name(name: Optional[str]) -> str:
    if not name:
        return ""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]", "", ascii_name.lower())


def _extract_posted_at(listing: Dict) -> Optional[str]:
    if listing.get("posted_at"):
        return listing["posted_at"]
    if listing.get("creation_date"):
        return listing["creation_date"]
    creation_time = listing.get("creation_time")
    if isinstance(creation_time, (int, float)):
        tz = datetime.timezone(datetime.timedelta(hours=2))
        return datetime.datetime.fromtimestamp(creation_time, tz=tz).isoformat()
    return None


def _load() -> Dict:
    if STORE_FILE.exists():
        try:
            return json.loads(STORE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"sellers": {}}


def _save(data: Dict) -> None:
    STORE_FILE.parent.mkdir(exist_ok=True)
    STORE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _seller_key(site: str, seller_id: str) -> str:
    return f"{site}:{seller_id}"


def record_matches(site: str, listings: List[Dict]) -> List[Dict]:
    data = _load()
    sellers = data["sellers"]
    newly_added: List[Dict] = []
    now = datetime.datetime.now().isoformat()

    for listing in listings:
        seller = listing.get("seller") or {}
        seller_id = seller.get("id")
        if not seller_id:
            continue

        seller_id = str(seller_id)
        key = _seller_key(site, seller_id)
        entry = sellers.setdefault(key, {
            "site": site,
            "seller_id": seller_id,
            "seller_name": seller.get("name"),
            "first_seen": now,
            "listings": [],
        })
        entry["seller_name"] = seller.get("name") or entry["seller_name"]
        entry["last_seen"] = now

        listing_id = str(listing.get("id"))
        if any(l["listing_id"] == listing_id for l in entry["listings"]):
            continue  
        record = {
            "listing_id": listing_id,
            "title": listing.get("title"),
            "price": listing.get("price"),
            "location": listing.get("location"),
            "image_url": listing.get("image_url"),
            "url": listing.get("url"),
            "matched_model": listing.get("_matched_model"),
            "posted_at": _extract_posted_at(listing),
            "detected_at": now,
        }
        entry["listings"].append(record)
        newly_added.append({**record, "site": site, "seller_id": seller_id, "seller_name": entry["seller_name"]})

    _save(data)
    return newly_added


def selling_pattern(listings: List[Dict]) -> str:
    dates = []
    for l in listings:
        raw = l.get("posted_at") or l.get("detected_at")
        if not raw:
            continue
        try:
            dates.append(datetime.datetime.fromisoformat(raw))
        except ValueError:
            continue
    if len(dates) < 2:
        return "insuffisant"
    dates.sort()
    return "échelonné" if (dates[-1] - dates[0]) > BATCH_THRESHOLD else "groupé"


def known_suspects(min_listings: int = 2) -> List[Dict]:
    data = _load()
    return [entry for entry in data["sellers"].values() if len(entry["listings"]) >= min_listings]


def cross_site_groups() -> List[List[Dict]]:
    data = _load()
    by_name: Dict[str, List[Dict]] = {}
    for entry in data["sellers"].values():
        norm = _normalize_name(entry.get("seller_name"))
        if not norm:
            continue
        by_name.setdefault(norm, []).append(entry)

    return [entries for entries in by_name.values() if len({e["site"] for e in entries}) >= 2]


SITE_LABELS = {
    "facebook": "Facebook Marketplace",
    "2ememain": "2ememain.be",
    "vinted": "Vinted",
}

GEOCODE_USER_AGENT = "stihl-tracker/1.0 (usage local, contact: repo owner)"
GEOCODE_RATE_LIMIT_SECONDS = 1.0


def _parse_price(raw) -> Optional[float]:
    if not raw:
        return None
    match = re.search(r"(\d+(?:[.,]\d+)?)", str(raw))
    if not match:
        return None
    return float(match.group(1).replace(",", "."))


def _primary_location(location: str) -> str:
    return location.split(" + ")[0].strip()


def _load_geocode_cache() -> Dict:
    if GEOCODE_CACHE_FILE.exists():
        try:
            return json.loads(GEOCODE_CACHE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_geocode_cache(cache: Dict) -> None:
    GEOCODE_CACHE_FILE.parent.mkdir(exist_ok=True)
    GEOCODE_CACHE_FILE.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")


def _query_nominatim(query: str, countrycodes: str) -> Optional[List[float]]:
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode({
        "q": query,
        "format": "json",
        "limit": 1,
        "countrycodes": countrycodes,
    })
    req = urllib.request.Request(url, headers={"User-Agent": GEOCODE_USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            results = json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None
    if not results:
        return None
    return [float(results[0]["lat"]), float(results[0]["lon"])]


def _query_nominatim_be_fr(query: str) -> Optional[List[float]]:
    coords = _query_nominatim(query, "be")
    if coords:
        return coords
    time.sleep(GEOCODE_RATE_LIMIT_SECONDS)
    return _query_nominatim(query, "fr")


def _geocode(location: Optional[str], cache: Dict) -> tuple:
    if not location:
        return (None, None)
    key = _primary_location(location).lower()
    if not key:
        return (None, None)
    if key in cache:
        entry = cache[key]
        return tuple(entry) if entry else (None, None)

    coords = _query_nominatim_be_fr(_primary_location(location))
    cache[key] = coords
    time.sleep(GEOCODE_RATE_LIMIT_SECONDS)
    return tuple(coords) if coords else (None, None)


def to_dashboard_sellers() -> List[Dict]:
    data = _load()
    sellers = data.get("sellers", {})
    geocode_cache = _load_geocode_cache()
    cache_size_before = len(geocode_cache)

    by_name: Dict[str, set] = {}
    for entry in sellers.values():
        norm = _normalize_name(entry.get("seller_name"))
        if norm:
            by_name.setdefault(norm, set()).add(entry["site"])

    out = []
    for key, entry in sellers.items():
        norm = _normalize_name(entry.get("seller_name"))
        sites_for_name = sorted(by_name.get(norm, {entry["site"]}))
        is_cross_site = len(sites_for_name) >= 2
        is_suspect = len(entry["listings"]) >= 2
        status = "multi-site" if is_cross_site else ("suspect" if is_suspect else "normal")

        listings_out = []
        for l in entry["listings"]:
            lat, lon = _geocode(l.get("location"), geocode_cache)
            listings_out.append({
                "site": SITE_LABELS.get(entry["site"], entry["site"]),
                "model": l.get("matched_model"),
                "title": l.get("title"),
                "price": _parse_price(l.get("price")),
                "city": l.get("location"),
                "postedAt": l.get("posted_at") or l.get("detected_at"),
                "url": l.get("url"),
                "lat": lat,
                "lon": lon,
            })

        out.append({
            "id": key,
            "name": entry.get("seller_name") or "Inconnu",
            "status": status,
            "listingCount": len(entry["listings"]),
            "sitesUsed": [SITE_LABELS.get(s, s) for s in sites_for_name],
            "pattern": selling_pattern(entry["listings"]),
            "listings": listings_out,
        })

    if len(geocode_cache) != cache_size_before:
        _save_geocode_cache(geocode_cache)

    return out
