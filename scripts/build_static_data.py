import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scrapers import suspects

OUT_FILE = Path(__file__).parent.parent / "static" / "data" / "sellers.json"


def main() -> None:
    payload = suspects.to_dashboard_sellers()
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{len(payload)} vendeur(s) exporté(s) vers {OUT_FILE}")


if __name__ == "__main__":
    main()
