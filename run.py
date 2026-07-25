import asyncio
import datetime
import json
import sys
from pathlib import Path

from scrapers import facebook, deuxiememain, vinted, suspects

if sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

output = Path(__file__).parent / "results"
output.mkdir(exist_ok=True)

INTERVAL_SECONDS = 45 * 60


CURRENT_STAGE = {"name": None}


def _save(site_slug: str, results) -> None:
    out_file = output / f"stolen_stihl_{site_slug}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"Résultats sauvegardés dans {out_file}")


def _print_suspects_report() -> None:
    known = suspects.known_suspects(min_listings=2)
    if known:
        print("\n" + "#" * 60)
        print(f"ALARM: VENDEURS SUSPECTS CONNUS (historique complet) : {len(known)}")
        for entry in known:
            pattern = suspects.selling_pattern(entry["listings"])
            print(
                f"ALARM:   [{entry['site']}] {entry['seller_name']} (id: {entry['seller_id']}) "
                f"— {len(entry['listings'])} annonce(s), vente {pattern}"
            )
            for l in entry["listings"]:
                print(f"ALARM:     → {l['title']}  |  {l['price']}  |  posté: {l.get('posted_at', '?')}  |  {l['url']}")
        print("#" * 60 + "\n")

    groups = suspects.cross_site_groups()
    if groups:
        print("\n" + "#" * 60)
        print(f"ALARM: CORRESPONDANCES POSSIBLES ENTRE SITES (même nom, à vérifier manuellement) : {len(groups)}")
        for group in groups:
            sites_desc = ", ".join(f"{e['site']} (id:{e['seller_id']})" for e in group)
            print(f"ALARM:   {group[0]['seller_name']} → {sites_desc}")
        print("#" * 60 + "\n")


async def run_once():
    new_alerts = []

    CURRENT_STAGE["name"] = "Facebook Marketplace"
    print(f"\n=== Facebook Marketplace ({datetime.datetime.now().strftime('%H:%M:%S')}) ===")
    try:
        fb_results = await facebook.scrape_stolen_stihl_tools()
    except Exception as exc:
        print(f"Erreur Facebook Marketplace : {exc}")
        fb_results = []
    next_run_anchor = datetime.datetime.now()
    _save("facebook", fb_results)
    new_alerts.extend(suspects.record_matches("facebook", fb_results))

    CURRENT_STAGE["name"] = "2ememain.be"
    print(f"\n=== 2ememain.be ({datetime.datetime.now().strftime('%H:%M:%S')}) ===")
    try:
        dm_results = deuxiememain.scrape_stolen_stihl_tools()
    except Exception as exc:
        print(f"Erreur 2ememain.be : {exc}")
        dm_results = []
    _save("2ememain", dm_results)
    new_alerts.extend(suspects.record_matches("2ememain", dm_results))

    CURRENT_STAGE["name"] = "Vinted"
    print(f"\n=== Vinted ({datetime.datetime.now().strftime('%H:%M:%S')}) ===")
    try:
        vt_results = vinted.scrape_stolen_stihl_tools()
    except Exception as exc:
        print(f"Erreur Vinted : {exc}")
        vt_results = []
    _save("vinted", vt_results)
    new_alerts.extend(suspects.record_matches("vinted", vt_results))

    CURRENT_STAGE["name"] = None

    if new_alerts:
        print(f"\nALARM: Nouvelles alertes ce passage (3 sites) : {len(new_alerts)}")
        for a in new_alerts:
            print(f"ALARM:   [{a['site']}] [{a['matched_model']}] {a['title']}  |  {a['price']}  |  {a['url']}")
    else:
        print("\nAucune nouvelle alerte ce passage (annonces déjà connues ou aucune correspondance).")

    _print_suspects_report()

    return new_alerts, next_run_anchor


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
