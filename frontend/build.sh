#!/usr/bin/env bash
# Builds one of the two finder frontends, with the page description derived from the index itself.
#
# Why this script exists. The live GeoDB page carried "12 037 Indikatoren, Tabellen und Datensätze
# aus 33 amtlichen Quellen" in its meta description, and that sentence existed NOWHERE in the repo:
# it had been passed on the command line of an ad hoc build. Two consequences, both silent. A
# rebuild with the documented command would have written the literal placeholder
# %VITE_PAGE_DESCRIPTION% into the page, which is what Vite does with an unset variable and what
# Google would then have shown as the snippet. And the number went stale the moment the index grew,
# which it did: 12,497 records from 41 sources on 2026-09-07.
#
# So the description is composed here from geodb_build_info.json, the file the index build writes,
# and the INKAR corpus beside it. The number cannot drift from the index any more.
#
#   bash frontend/build.sh inkar          # writes dist-inkar
#   bash frontend/build.sh soep           # writes dist-soep
#   bash frontend/build.sh inkar --print  # only show what it would pass, build nothing
set -euo pipefail
HIER="$(cd "$(dirname "$0")" && pwd)"
WURZEL="$(cd "$HIER/.." && pwd)"
MODUS="${1:?usage: build.sh <inkar|soep> [--print]}"
NUR_ZEIGEN="${2:-}"

zahlen() {
  "$HOME/miniconda3/bin/python3" - "$WURZEL" <<'PY'
import json, sys
from pathlib import Path
wurzel = Path(sys.argv[1]) / "soep_metadata_output"
info = json.loads((wurzel / "geodb_build_info.json").read_text())
inkar = json.loads((wurzel / "inkar_metadata_2025.json").read_text())
anzahl = int(info["records"]) + len(inkar if isinstance(inkar, list) else inkar.get("records", []))
print(f"{anzahl:,}".replace(",", " "), info["sources"], sep="|")
PY
}

# The IndexNow keys. IndexNow is the push protocol Bing, Yandex, Seznam and Naver share: the key
# file must be reachable on the host it belongs to, and it is public by design, so it lives here in
# the open rather than in the secret store. Google does not take part.
SCHLUESSEL_INKAR="c04526153e934b868ca03bac447c00a8"
SCHLUESSEL_SOEP="aa34e73bd5704a4081b983d0f2ca2534"

case "$MODUS" in
  inkar)
    IFS="|" read -r DATENSAETZE QUELLEN <<<"$(zahlen)"
    TITEL="GeoDB Geodata Index"
    BESCHREIBUNG="Semantische Suche in Beschreibungen deutscher Geodaten: ${DATENSAETZE} Indikatoren, Tabellen und Datensätze aus ${QUELLEN} Datenquellen. Nur Metadaten."
    AUSGABE="dist-inkar"
    ADRESSE="https://geodb.geolab.soz.uni-bielefeld.de/"
    DOI="https://doi.org/10.5281/zenodo.21134145"
    SCHLUESSEL="$SCHLUESSEL_INKAR"
    ;;
  soep)
    TITEL="SOEP Variable Finder"
    BESCHREIBUNG="Semantische Suche in den Variablenbeschreibungen des SOEP-Core v41. Nur Metadaten."
    AUSGABE="dist-soep"
    ADRESSE="https://soep-faiss.geolab.soz.uni-bielefeld.de/"
    DOI="https://doi.org/10.5281/zenodo.21134306"
    SCHLUESSEL="$SCHLUESSEL_SOEP"
    ;;
  *) echo "unknown mode: $MODUS (inkar|soep)"; exit 2 ;;
esac

echo "mode=$MODUS  out=$AUSGABE"
echo "title=$TITEL"
echo "url=$ADRESSE"
echo "description=$BESCHREIBUNG"
[[ "$NUR_ZEIGEN" == "--print" ]] && exit 0

cd "$HIER"
PATH="$HOME/miniconda3/envs/nodejs/bin:$PATH" \
  VITE_APP_MODE="$MODUS" VITE_PAGE_TITLE="$TITEL" VITE_PAGE_DESCRIPTION="$BESCHREIBUNG" \
  VITE_SITE_URL="$ADRESSE" VITE_DOI="$DOI" \
  node node_modules/.bin/vite build --outDir "$AUSGABE" --emptyOutDir

# Crawler files. Caddy serves these as real files because the site block tries {path} before it
# falls back to the app shell; until 2026-09-07 both hosts answered /robots.txt and /sitemap.xml
# with that shell as text/html, so a search engine got an HTML document where the rules and the
# URL list should have been, and a submitted sitemap could not be parsed at all.
cat > "$AUSGABE/robots.txt" <<ROBOTS
# Everything here is public metadata and meant to be found.
User-agent: *
Allow: /
# Nothing is blocked on purpose. A first version disallowed /api/, which looked tidy and was wrong:
# the app fetches /api/soep/filter-options to render, so a crawler denied that path renders an empty
# form and indexes it. The API itself answers POST queries and has no crawlable pages.

Sitemap: ${ADRESSE}sitemap.xml
ROBOTS

cat > "$AUSGABE/sitemap.xml" <<KARTE
<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>${ADRESSE}</loc>
    <lastmod>$(date +%F)</lastmod>
    <changefreq>monthly</changefreq>
    <priority>1.0</priority>
  </url>
</urlset>
KARTE

printf '%s' "$SCHLUESSEL" > "$AUSGABE/$SCHLUESSEL.txt"
echo "wrote robots.txt, sitemap.xml and the IndexNow key file into $AUSGABE"
