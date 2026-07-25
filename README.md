Surveillance d'outils Stihl volés sur 3 sites : Facebook Marketplace, 2ememain.be, Vinted.

## Installation
```
pip install playwright loguru flask
python -m playwright install chromium
python -m playwright install-deps chromium   # Linux uniquement : librairies système pour Chromium headless
```
(Playwright n'est utilisé que pour Facebook Marketplace ; 2ememain.be et Vinted n'ont pas besoin de navigateur.)

## Lancement en ligne de commande
```
python run.py
```
Enchaîne Facebook Marketplace → 2ememain.be → Vinted, puis attend jusqu'à 45 min après la fin
de Facebook Marketplace avant de relancer un passage complet.

## Interface web locale (console, alerte, timer, export des logs)
```
python web.py
```
Puis ouvrir http://127.0.0.1:8000 (accessible aussi depuis le réseau local sur ce port).

## Structure
- `scrapers/facebook.py`, `scrapers/deuxiememain.py`, `scrapers/vinted.py` — un module par site,
  même logique de détection (modèles volés, alerte vendeur suspect).
- `run.py` — orchestrateur séquentiel + minuteur des 45 min.
- `web.py` + `static/` — interface web unique pour les 3 sites.
- `results/` — un JSON de résultats et un cache d'annonces déjà vues par site.
