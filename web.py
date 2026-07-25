import asyncio
import datetime
import logging
import re
import sys
import threading
import time
from pathlib import Path

BASE_DIR = Path(__file__).parent


class _TeeStream:
    
    def __init__(self, original):
        self._original = original
        self._pending = ""

    def write(self, text):
        self._original.write(text)
        self._pending += text
        while "\n" in self._pending:
            line, self._pending = self._pending.split("\n", 1)
            _append_log(line)
        return len(text)

    def flush(self):
        self._original.flush()

    def isatty(self):
        return False

    def __getattr__(self, name):
        return getattr(self._original, name)


MAX_LOADED_LOGS = 4000

_lock = threading.Lock()
_log_lines: list[str] = []
_state = {
    "running": False,
    "current_stage": None,
    "alarm": False,
    "alarm_count": 0,
    "next_run_at": None,
    "last_run_at": None,
}


def _append_log(line: str) -> None:
    if not line:
        return
    formatted = f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {line}"
    with _lock:
        _log_lines.append(formatted)
        if len(_log_lines) > MAX_LOADED_LOGS:
            del _log_lines[: len(_log_lines) - MAX_LOADED_LOGS]
        logdb.append(formatted)


sys.stdout = _TeeStream(sys.stdout)
sys.stderr = _TeeStream(sys.stderr)

from scrapers import logdb, suspects  # noqa: E402
import run as scraper  # noqa: E402
from flask import Flask, Response, jsonify, request  # noqa: E402

logging.getLogger("werkzeug").setLevel(logging.WARNING)

app = Flask(__name__, static_folder=str(BASE_DIR / "static"), static_url_path="")


def _scraper_loop() -> None:
    while True:
        with _lock:
            _state["running"] = True
        try:
            results, anchor = asyncio.run(scraper.run_once())
            with _lock:
                _state["alarm"] = len(results) > 0
                _state["alarm_count"] = len(results)
                _state["last_run_at"] = datetime.datetime.now().isoformat()
        except Exception as exc:
            print(f"Erreur pendant le passage : {exc}")
            anchor = datetime.datetime.now()

        next_run = anchor + datetime.timedelta(seconds=scraper.INTERVAL_SECONDS)
        with _lock:
            _state["running"] = False
            _state["current_stage"] = None
            _state["next_run_at"] = next_run.isoformat()
        print(f"Prochain passage à {next_run.strftime('%H:%M:%S')} (45 min après la fin de Facebook Marketplace)")

        wait_seconds = (next_run - datetime.datetime.now()).total_seconds()
        if wait_seconds > 0:
            time.sleep(wait_seconds)


def _stage_watcher() -> None:
    while True:
        with _lock:
            _state["current_stage"] = scraper.CURRENT_STAGE["name"]
        time.sleep(1)


@app.route("/")
def index():
    return app.send_static_file("index.html")


@app.route("/dashboard")
def dashboard():
    return app.send_static_file("dashboard.html")


@app.route("/api/suspects")
def api_suspects():
    data = suspects._load()
    sellers = data.get("sellers", {})

    by_name: dict[str, set[str]] = {}
    for entry in sellers.values():
        norm = suspects._normalize_name(entry.get("seller_name"))
        if norm:
            by_name.setdefault(norm, set()).add(entry["site"])

    out = []
    for key, entry in sellers.items():
        norm = suspects._normalize_name(entry.get("seller_name"))
        sites_for_name = by_name.get(norm, set())
        out.append({
            **entry,
            "key": key,
            "is_suspect": len(entry["listings"]) >= 2,
            "is_cross_site": len(sites_for_name) >= 2,
            "cross_site_platforms": sorted(sites_for_name),
            "selling_pattern": suspects.selling_pattern(entry["listings"]),
        })

    return jsonify({"sellers": out})


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


def _parse_price(raw) -> float | None:
    if not raw:
        return None
    match = re.search(r"(\d+(?:[.,]\d+)?)", str(raw))
    if not match:
        return None
    return float(match.group(1).replace(",", "."))


def _geocode(location) -> tuple:
    if not location:
        return (None, None)
    key = location.strip().lower()
    return CITY_COORDS.get(key, (None, None))


@app.route("/api/sellers")
def api_sellers():
    data = suspects._load()
    sellers = data.get("sellers", {})

    by_name: dict[str, set[str]] = {}
    for entry in sellers.values():
        norm = suspects._normalize_name(entry.get("seller_name"))
        if norm:
            by_name.setdefault(norm, set()).add(entry["site"])

    out = []
    for key, entry in sellers.items():
        norm = suspects._normalize_name(entry.get("seller_name"))
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
            "pattern": suspects.selling_pattern(entry["listings"]),
            "listings": listings_out,
        })

    return jsonify(out)


@app.route("/api/state")
def api_state():
    with _lock:
        return jsonify(dict(_state))


@app.route("/api/logs")
def api_logs():
    since = request.args.get("since", default=0, type=int)
    with _lock:
        lines = _log_lines[since:]
        total = len(_log_lines)
    return jsonify({"lines": lines, "total": total})


@app.route("/api/export")
def api_export():
    with _lock:
        content = "\n".join(_log_lines)
    filename = f"scraper_log_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    return Response(
        content,
        mimetype="text/plain",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


def main():
    with _lock:
        _log_lines.extend(logdb.load_recent(MAX_LOADED_LOGS))
    threading.Thread(target=_scraper_loop, daemon=True).start()
    threading.Thread(target=_stage_watcher, daemon=True).start()
    print("Interface dispo sur http://127.0.0.1:8000 (et en local : port 8000)")
    app.run(host="0.0.0.0", port=8000, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
