import asyncio
import datetime
import json
import logging
import subprocess
import sys
import threading
import time
from pathlib import Path

BASE_DIR = Path(__file__).parent
STATIC_DATA_FILE = BASE_DIR / "static" / "data" / "sellers.json"
PUBLISH_BRANCH = "valentin"


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
            _publish_snapshot()
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


def _current_branch() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=BASE_DIR, capture_output=True, text=True, check=True,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, OSError):
        return ""


def _publish_snapshot() -> None:
    if _current_branch() != PUBLISH_BRANCH:
        return
    try:
        STATIC_DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATIC_DATA_FILE.write_text(
            json.dumps(suspects.to_dashboard_sellers(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        subprocess.run(["git", "add", str(STATIC_DATA_FILE)], cwd=BASE_DIR, check=True)
        diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=BASE_DIR)
        if diff.returncode == 0:
            return
        subprocess.run(
            ["git", "commit", "-m", "Data update"],
            cwd=BASE_DIR, check=True,
        )
        subprocess.run(["git", "push", "origin", PUBLISH_BRANCH], cwd=BASE_DIR, check=True)
        print(f"Snapshot on Netlify (branch {PUBLISH_BRANCH})")
    except (subprocess.CalledProcessError, OSError) as exc:
        print(f"Erreur lors de la publication du snapshot : {exc}")


@app.route("/")
def index():
    return app.send_static_file("index.html")


@app.route("/dashboard")
def dashboard():
    return app.send_static_file("dashboard.html")


@app.route("/api/sellers")
def api_sellers():
    return jsonify(suspects.to_dashboard_sellers())


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
