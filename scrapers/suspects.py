import datetime
import json
import re
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional

STORE_FILE = Path(__file__).parent.parent / "results" / "suspects.json"

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

CITY_COORDS = {
    "willebroek": (51.0667, 4.3667),
    "heppen": (51.0833, 5.3667),
    "bilzen": (50.8703, 5.5167),
    "bruxelles": (50.8503, 4.3517),
    "brussel": (50.8503, 4.3517),
    "antwerpen": (51.2194, 4.4025),
    "gent": (51.0543, 3.7174),
    "liege": (50.6326, 5.5797),
    "liège": (50.6326, 5.5797),
    "charleroi": (50.4114, 4.4445),
    "namur": (50.4669, 4.8675),
    "mons": (50.4542, 3.9523),
    "leuven": (50.8798, 4.7005),
    "brugge": (51.2093, 3.2247),
    "lille": (50.6292, 3.0573),
    "douai": (50.3714, 3.0797),
    "valenciennes": (50.3574, 3.5233),
}


def _parse_price(raw) -> Optional[float]:
    if not raw:
        return None
    match = re.search(r"(\d+(?:[.,]\d+)?)", str(raw))
    if not match:
        return None
    return float(match.group(1).replace(",", "."))


def _geocode(location: Optional[str]) -> tuple:
    if not location:
        return (None, None)
    return CITY_COORDS.get(location.strip().lower(), (None, None))


def to_dashboard_sellers() -> List[Dict]:
    data = _load()
    sellers = data.get("sellers", {})

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
            lat, lon = _geocode(l.get("location"))
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

    return out
