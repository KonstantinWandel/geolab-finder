#!/usr/bin/env bash
# Richtet den wöchentlichen Zustandsbericht auf der geolab-VM ein. Von lovelace aus laufen lassen.
#
# Warum auf der VM: sie ist eine echte Maschine mit Cron und übersteht einen Neustart. lovelace
# ist ein Pod, dessen /etc beim Neubau geleert wird, also hält dort kein Zeitplan. Der Prüflauf
# braucht keine GPU, nur Netz.
#
# Der Aufruf ist wiederholbar: er legt nur an, was fehlt, und bringt Skripte, Registry und die
# Liste der anerkannten Ausnahmen jedes Mal auf den neuesten Stand. Nach jeder Änderung an einer
# dieser Dateien also erneut aufrufen.
#
#   bash scripts/install_health_check.sh
#   bash scripts/install_health_check.sh --run    # danach einmal vollständig prüfen
set -euo pipefail
cd "$(dirname "$0")/.."
VM=${GEOLAB_VM:-vm}
REMOTE=/home/kwandel/health

echo "[1/5] Skripte, Registry und Ausnahmen übertragen"
ssh "$VM" "mkdir -p $REMOTE/repo/scripts $REMOTE/repo/data_sources/registry $REMOTE/repo/state $REMOTE/repo/logs"
rsync -az scripts/health_check.py scripts/check_source_urls.py scripts/check_geodb_links.py \
      "$VM:$REMOTE/repo/scripts/"
rsync -az data_sources/registry/geo_sources.json data_sources/registry/known_url_issues.json \
      "$VM:$REMOTE/repo/data_sources/registry/"
# Die Anleitung liegt auch auf der VM, damit sie dort greifbar ist, wo etwas kaputt ist.
rsync -az MAINTENANCE.md "$VM:$REMOTE/MAINTENANCE.md"

echo "[2/5] Metadaten verlinken (die geprüften Links stehen im ausgelieferten Index)"
ssh "$VM" "ln -sfn /opt/geolab/app/destatis-rag/soep_metadata_output $REMOTE/repo/soep_metadata_output"

echo "[3/5] Python mit Browser (nur beim ersten Mal, ~500 MB)"
ssh "$VM" bash -s <<'REMOTE_SH'
set -euo pipefail
R=/home/kwandel/health
if [[ ! -x $R/venv/bin/python ]]; then
  sudo -n apt-get install -y python3-venv >/dev/null 2>&1 || true
  python3 -m venv $R/venv
  $R/venv/bin/pip -q install --upgrade pip playwright
  sudo -n $R/venv/bin/playwright install-deps chromium >/dev/null 2>&1 || \
    echo "  Hinweis: Systembibliotheken für Chromium nicht installiert, Adressprüfung faellt aus"
  $R/venv/bin/playwright install chromium
else
  echo "  vorhanden"
fi
$R/venv/bin/python -c "import playwright; print('  playwright ok')"
REMOTE_SH

echo "[4/5] Startskript und Zeitplan"
ssh "$VM" bash -s <<'REMOTE_SH'
set -euo pipefail
R=/home/kwandel/health
cat > $R/run_health.sh <<'INNER'
#!/usr/bin/env bash
# Wöchentlicher Zustandsbericht. Ergebnis: repo/state/latest.json, Verlauf: repo/logs/health.log
R=/home/kwandel/health
exec >> "$R/logs/cron.out" 2>&1
echo "=== $(date -Is) Start"
python3 "$R/repo/scripts/health_check.py" --python "$R/venv/bin/python"
echo "=== $(date -Is) Ende, Rueckgabewert $?"
INNER
chmod +x $R/run_health.sh
# Montags 05:30, also nach der Sicherung um 04:15 und vor dem Arbeitstag.
entry="30 5 * * 1 /bin/bash $R/run_health.sh"
( crontab -l 2>/dev/null | grep -v "run_health.sh" ; echo "$entry" ) | crontab -
crontab -l | grep -c run_health.sh >/dev/null && echo "  Zeitplan gesetzt: $entry"
REMOTE_SH

if [[ "${1:-}" == "--run" ]]; then
  echo "[5/5] einmal vollständig prüfen (dauert einige Minuten)"
  ssh "$VM" "python3 $REMOTE/repo/scripts/health_check.py --python $REMOTE/venv/bin/python" || true
else
  echo "[5/5] Probelauf übersprungen (mit --run erzwingen)"
fi
