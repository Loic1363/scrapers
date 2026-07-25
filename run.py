import asyncio
import datetime
import json
import sys
from pathlib import Path

from scrapers import facebook, deuxiememain, vinted

if sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

output = Path(__file__).parent / "results"
output.mkdir(exist_ok=True)

INTERVAL_SECONDS = 45 * 60

# Étape en cours ("Facebook Marketplace" / "2ememain.be" / "Vinted" / None), lue par web.py.
CURRENT_STAGE = {"name": None}


def _save(site_slug: str, results) -> None:
    out_file = output / f"stolen_stihl_{site_slug}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"Résultats sauvegardés dans {out_file}")


async def run_once():
    """Lance les 3 sites en séquence : Facebook, puis 2ememain, puis Vinted.
    Le minuteur de 45 min avant le prochain passage démarre dès que Facebook a terminé
    (les deux autres sites tournent ensuite sans décaler ce repère)."""
    all_results = []

    CURRENT_STAGE["name"] = "Facebook Marketplace"
    print(f"\n=== Facebook Marketplace ({datetime.datetime.now().strftime('%H:%M:%S')}) ===")
    try:
        fb_results = await facebook.scrape_stolen_stihl_tools()
    except Exception as exc:
        print(f"Erreur Facebook Marketplace : {exc}")
        fb_results = []
    next_run_anchor = datetime.datetime.now()
    _save("facebook", fb_results)
    all_results.extend(fb_results)

    CURRENT_STAGE["name"] = "2ememain.be"
    print(f"\n=== 2ememain.be ({datetime.datetime.now().strftime('%H:%M:%S')}) ===")
    try:
        dm_results = deuxiememain.scrape_stolen_stihl_tools()
    except Exception as exc:
        print(f"Erreur 2ememain.be : {exc}")
        dm_results = []
    _save("2ememain", dm_results)
    all_results.extend(dm_results)

    CURRENT_STAGE["name"] = "Vinted"
    print(f"\n=== Vinted ({datetime.datetime.now().strftime('%H:%M:%S')}) ===")
    try:
        vt_results = vinted.scrape_stolen_stihl_tools()
    except Exception as exc:
        print(f"Erreur Vinted : {exc}")
        vt_results = []
    _save("vinted", vt_results)
    all_results.extend(vt_results)

    CURRENT_STAGE["name"] = None
    print(f"\nTotal annonces suspectes (3 sites) : {len(all_results)}")
    return all_results, next_run_anchor


async def run_forever():
    while True:
        results, anchor = await run_once()

        next_run = anchor + datetime.timedelta(seconds=INTERVAL_SECONDS)
        print(f"Prochain passage à {next_run.strftime('%H:%M:%S')} (45 min après la fin de Facebook Marketplace)")

        wait_seconds = (next_run - datetime.datetime.now()).total_seconds()
        if wait_seconds > 0:
            await asyncio.sleep(wait_seconds)


if __name__ == "__main__":
    try:
        asyncio.run(run_forever())
    except KeyboardInterrupt:
        print("\nArrêt.")
