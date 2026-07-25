import asyncio
import json
import sys
from pathlib import Path
import facebook

if sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

output = Path(__file__).parent / "results"
output.mkdir(exist_ok=True)


async def run():
    print("Lancement de la recherche...")
    results = await facebook.scrape_stolen_stihl_tools()

    out_file = output / "stolen_stihl.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\nRésultats sauvegardés dans {out_file}")
    print(f"Total annonces suspectes : {len(results)}")


if __name__ == "__main__":
    asyncio.run(run())
