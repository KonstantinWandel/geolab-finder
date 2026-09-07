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

case "$MODUS" in
  inkar)
    IFS="|" read -r DATENSAETZE QUELLEN <<<"$(zahlen)"
    TITEL="GeoDB Geodata Index"
    BESCHREIBUNG="Semantische Suche in Beschreibungen deutscher Geodaten: ${DATENSAETZE} Indikatoren, Tabellen und Datensätze aus ${QUELLEN} Datenquellen. Nur Metadaten."
    AUSGABE="dist-inkar"
    ;;
  soep)
    TITEL="SOEP Variable Finder"
    BESCHREIBUNG="Semantische Suche in den Variablenbeschreibungen des SOEP-Core v41. Nur Metadaten."
    AUSGABE="dist-soep"
    ;;
  *) echo "unknown mode: $MODUS (inkar|soep)"; exit 2 ;;
esac

echo "mode=$MODUS  out=$AUSGABE"
echo "title=$TITEL"
echo "description=$BESCHREIBUNG"
[[ "$NUR_ZEIGEN" == "--print" ]] && exit 0

cd "$HIER"
PATH="$HOME/miniconda3/envs/nodejs/bin:$PATH" \
  VITE_APP_MODE="$MODUS" VITE_PAGE_TITLE="$TITEL" VITE_PAGE_DESCRIPTION="$BESCHREIBUNG" \
  node node_modules/.bin/vite build --outDir "$AUSGABE" --emptyOutDir
