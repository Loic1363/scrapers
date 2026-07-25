"""Base persistante des vendeurs suspects : ne concerne que les annonces déjà identifiées
comme correspondant à un modèle volé (alerte). Sert à repérer les vendeurs qui écoulent les
objets un par un, avec des délais, plutôt que d'un coup (ce qui est un autre signal suspect
déjà couvert par l'alerte "vendeur" de chaque site pour une seule passe)."""
import datetime
import json
import re
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional

STORE_FILE = Path(__file__).parent.parent / "results" / "suspects.json"

BATCH_THRESHOLD = datetime.timedelta(hours=24)


def _normalize_name(name: Optional[str]) -> str:
    """Nom réduit à ses lettres/chiffres, sans accents ni casse, pour comparer un même
    vendeur potentiel entre deux sites différents (heuristique, pas une preuve)."""
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
    """Enregistre les annonces déjà identifiées comme suspectes (modèle volé reconnu) dans
    l'historique persistant du vendeur. Une annonce déjà connue (même site, même id
    d'annonce) n'est jamais réenregistrée ni resignalée. Retourne uniquement les annonces
    réellement nouvelles (jamais vues lors d'un passage précédent)."""
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
            continue  # déjà signalée pour ce vendeur, on ne la resignale pas

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
    """'groupé' si toutes les annonces connues sont apparues à moins de 24h d'écart
    (vente en bloc), 'échelonné' si des annonces sont espacées de plus de 24h (vente au
    compte-goutte, un signal souvent plus discret donc plus suspect sur la durée)."""
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
    """Tous les vendeurs (tous sites, tous passages confondus) ayant au moins
    `min_listings` annonces correspondant à un modèle volé."""
    data = _load()
    return [entry for entry in data["sellers"].values() if len(entry["listings"]) >= min_listings]


def cross_site_groups() -> List[List[Dict]]:
    """Regroupe, par nom de vendeur normalisé, les vendeurs qui semblent présents sur
    plusieurs sites différents. Heuristique par nom uniquement : un nom identique ne
    prouve pas qu'il s'agit de la même personne, à vérifier manuellement."""
    data = _load()
    by_name: Dict[str, List[Dict]] = {}
    for entry in data["sellers"].values():
        norm = _normalize_name(entry.get("seller_name"))
        if not norm:
            continue
        by_name.setdefault(norm, []).append(entry)

    return [entries for entries in by_name.values() if len({e["site"] for e in entries}) >= 2]
