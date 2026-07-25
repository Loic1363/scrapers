import asyncio
import datetime
import json
import sys
from pathlib import Path
import facebook

if sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

output = Path(__file__).parent / "results"
output.mkdir(exist_ok=True)

INTERVAL_SECONDS = 45 * 60


async def run_once():
    print(f"\nLancement de la recherche... ({datetime.datetime.now().strftime('%H:%M:%S')})")
    results = await facebook.scrape_stolen_stihl_tools()

    out_file = output / "stolen_stihl.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"Résultats sauvegardés dans {out_file}")
    print(f"Total annonces suspectes : {len(results)}")


async def run_forever():
    while True:
        try:
            await run_once()
        except Exception as exc:
            print(f"Erreur pendant le passage : {exc}")

        next_run = datetime.datetime.now() + datetime.timedelta(seconds=INTERVAL_SECONDS)
        print(f"Prochain passage à {next_run.strftime('%H:%M:%S')}")
        await asyncio.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    try:
        asyncio.run(run_forever())
    except KeyboardInterrupt:
        print("\nArrêt.")
