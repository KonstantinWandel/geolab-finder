# Wartung der beiden Metadatenfinder

Für die Person, die das übernimmt. Kein Vorwissen über das Projekt nötig, aber ein Terminal, ein
SSH-Zugang zur geolab-VM und die Bereitschaft, einmal im Monat zehn Minuten hineinzusehen.

Die technische Innenansicht steht in `CLAUDE.md` und richtet sich an KI-Agenten. Dieses Dokument
hier ist die Bedienungsanleitung: was von selbst läuft, was du tun musst, und was zu tun ist, wenn
etwas kaputt ist.

## Was es gibt

| Was | Adresse |
|---|---|
| GeoDB Geodata Index (36 Datenquellen, 11.377 Datensätze) | <https://geodb.geolab.soz.uni-bielefeld.de> |
| SOEP Variable Finder (125.496 Variablen aus SOEP-Core v41) | <https://soep-faiss.geolab.soz.uni-bielefeld.de> |
| Projektseite | <https://geolab.soz.uni-bielefeld.de> |

Beide Seiten sind Suchmaschinen für Metadaten. Sie halten keine Forschungsdaten, sondern
beschreiben, welche Daten es gibt und wo sie liegen, und verlinken dorthin. **Der Link ist das
Produkt.** Wenn er ins Leere führt, ist der Finder wertlos, auch wenn die Suche gut funktioniert.
Deshalb dreht sich die Wartung fast vollständig um die Frage, ob die Links noch stimmen.

Zitierbar über Zenodo: GeoDB `10.5281/zenodo.21134145`, SOEP Variable Finder
`10.5281/zenodo.21134306`. Quelltext: <https://github.com/KonstantinWandel/geolab-finder> und
<https://github.com/KonstantinWandel/soep-variable-finder>.

## Welche Maschine was tut

| Maschine | Rolle | Zugang |
|---|---|---|
| **geolab-VM** (`ssh vm`, 129.70.40.104) | betreibt beide Seiten: Caddy auf 443, zwei uvicorn-Dienste, der wöchentliche Prüflauf, die tägliche Auslagerung | echte VM, übersteht Neustarts, `sudo` ohne Passwort |
| **lovelace** (dieser Rechner) | Entwicklung, Neuaufbau des Index auf der GPU, Auslieferung zur VM | Kubernetes-Pod: alles außer `$HOME` ist beim Neustart weg |

Das ist der Grund für die Arbeitsteilung: **Zeitpläne gehören auf die VM**, weil auf lovelace kein
Cron einen Neustart übersteht. **Der Neuaufbau des Index bleibt auf lovelace**, weil er eine GPU
braucht (zwei Minuten dort, eine Stunde auf der VM).

## Was von selbst läuft

| Was | Wann | Wo nachzulesen |
|---|---|---|
| Zustandsbericht (Links, Adressen, Dienste, Zertifikat, Platte) | montags 05:30, VM | `ssh vm "cat /home/kwandel/health/repo/state/latest.json"`, Verlauf in `logs/health.log` |
| Auslagerung nach Kühne-Share | täglich 04:15, VM | `ssh vm "tail -3 ~/backup_sync/logs/sync_geolab.log"` |
| Caddy neu laden, wenn das Zertifikat ausgetauscht wurde | bei jeder Änderung der Datei | `ssh vm "systemctl status caddy-cert-reload.path"` |
| Dienst neu starten, wenn er nicht antwortet | im Prüflauf | steht als `selbstheilung` im Bericht |
| Hinweis beim Einloggen auf lovelace, wenn der Bericht nicht grün ist | bei jedem Login, höchstens zwölfstündlich | `bash ~/kwandel/bin/geolab_alarm.sh` |

Ein grüner Bericht schweigt. Wenn beim Einloggen nichts erscheint, ist alles in Ordnung. Nach einer
Selbstheilung wird der Bericht **gelb**, nicht grün: ein Dienst, der jede Woche neu gestartet werden
muss, ist kaputt, auch wenn jeder Neustart klappt.

## Routine 1: einmal im Monat hineinsehen (10 Minuten)

```bash
ssh vm "cat /home/kwandel/health/repo/logs/health.log | tail -8"
```

Eine Zeile pro Lauf. `OK` heißt alles gut, `WARN` beobachten, `BAD` handeln. Die Spalten:

- `dienst` beide Finder haben auf eine echte Frage mit mehr als null Treffern geantwortet.
  Absichtlich keine `/health`-Abfrage: ein Dienst mit fehlendem Index antwortet dort weiter mit
  „ok" und liefert null Treffer, und das ist der Ausfall, der ohne echte Frage niemandem auffällt.
- `quellen` die 36 Einstiegsseiten der Datenquellen, im echten Browser geprüft.
- `links` Anteil der geprüften Tiefenlinks, die Inhalt geliefert haben (Stichprobe von etwa 420
  pro Woche, wandert über die Wochen durch den Bestand). Unter 0,90 gelb, unter 0,75 rot.
- `alter` Alter des Index in Tagen. Über 200 gelb, über 400 rot.
- `zert` das ausgelieferte Zertifikat gegen das auf der Platte.
- `maschine` Plattenplatz und Auslagerung.

Bei `WARN` oder `BAD` den vollen Bericht lesen:

```bash
ssh vm "python3 -m json.tool /home/kwandel/health/repo/state/latest.json"
```

## Routine 2: eine Quellenadresse ist rot

Der häufigste Fall, und der einzige, der wirklich Urteilsvermögen braucht. Portale ziehen um,
Behörden werden umbenannt, Projekte werden abgeschaltet, Domains verfallen.

**Erst nachsehen, was wirklich passiert ist.** Im Bericht steht unter `quellen` entweder
`domain_verlassen` (die Adresse antwortet, führt aber woandershin) oder `tot`. Die Adresse im
eigenen Browser öffnen und entscheiden, welcher der vier Fälle es ist:

1. **Das Portal ist umgezogen.** Neue Adresse in `SOURCE_FIXES` in
   `scripts/build_source_registry.py` eintragen, mit Grund und Datum. Die alte Adresse wandert
   automatisch nach `url_former`, damit der Umzug nachlesbar bleibt.
2. **Die Seite lebt, ist aber von außen nicht prüfbar** (Bot-Schutz, Anmeldung). Eintrag in
   `data_sources/registry/known_url_issues.json` mit Grund, Datum und einem Datum zur
   Wiedervorlage. Der Prüflauf schweigt dann darüber, meldet sich aber wieder, wenn die
   Wiedervorlage fällig ist.
3. **Die Domain ist verfallen und gehört jetzt jemand anderem.** Das ist der schlimme Fall: die
   Antwort ist 200, der Finder würde Nutzer auf eine fremde Firmenseite schicken. Adresse sofort
   auf eine unverdächtige Ersatzseite umbiegen (`SOURCE_FIXES`), die alte in der
   Wartungsnotiz festhalten, den Betreiber informieren. So geschehen mit
   `breitband-monitor.de`, das auf eine Firmenseite umleitete.
4. **Das Angebot ist eingestellt.** Nichts löschen. Historische Metadaten bleiben zitierbar. In
   der Wartungsnotiz vermerken, dass es eingestellt ist; der Finder erkennt Wörter wie
   „eingestellt" und „abgeschaltet" und schreibt einen Hinweis in die Beschreibung.

**Adressen werden nur an einer Stelle korrigiert**, in `SOURCE_FIXES`. Die Registry
`data_sources/registry/geo_sources.json` wird aus einer Excel-Arbeitsmappe erzeugt, deshalb hält
eine dort von Hand eingetragene Korrektur nur bis zum nächsten Neuaufbau und verschwindet dann
mitsamt der Begründung. Genau das war vier Adressen und acht Notizen schon passiert.

Danach neu erzeugen und ausliefern:

```bash
cd ~/kwandel/destatis-rag
~/miniconda3/envs/geolab-rag/bin/python scripts/build_source_registry.py --no-scaffold
bash scripts/install_health_check.sh          # bringt der VM die neue Registry
bash scripts/refresh_all.sh                   # erst wenn die Korrektur in den Finder soll
```

## Routine 3: den Index neu bauen (halbjährlich, etwa eine Stunde)

Ein Befehl macht alles: neu holen, neu bauen, auf der GPU neu einbetten, Adressen prüfen,
Suchqualität messen, ausliefern, Statusbericht erzeugen.

```bash
cd ~/kwandel/destatis-rag
bash scripts/refresh_all.sh              # mit Auslieferung
bash scripts/refresh_all.sh --no-deploy  # nur bauen und messen, nichts anfassen
```

**Vor dem Ausliefern auf Schritt [4/6] achten**, das ist die Suchqualitätsprüfung. Wenn dort
deutlich mehr Fälle scheitern als vorher (der Stand ist in `output/eval_latest.json` festgehalten),
nicht ausliefern, sondern nachsehen, was am Index anders ist. Ausliefern kann man immer noch.

Danach prüfen, dass die Seiten wirklich das Neue zeigen:

```bash
curl -s https://geodb.geolab.soz.uni-bielefeld.de/ | grep -o 'assets/index-[A-Za-z0-9_-]*\.js'
grep -o 'assets/index-[A-Za-z0-9_-]*\.js' frontend/dist-inkar/index.html
```

Beide Zeichenketten müssen gleich sein. Ein fehlgeschlagener Frontend-Bau liefert sonst
unbemerkt das alte Bündel aus, und `rsync` meldet trotzdem Erfolg.

**Alte Bündel nie löschen.** Wer die Seite schon einmal besucht hat, kann noch ein älteres
`index.html` im Browser haben und fragt dann nach einem alten Bündelnamen. Fehlt der, sah der
Besucher bis zum 2026-09-05 einen weißen Bildschirm, und zwar dauerhaft, weil der Server die
fehlende Datei mit `200`, HTML-Inhalt und einem Jahr Cache beantwortet hat. Der Server sagt jetzt
sauber `404`, und die Bündel werden beim Ausliefern nur ergänzt, nicht ersetzt (`rsync` ohne
`--delete` für `assets/`). Der Wochenbericht prüft beides.

**Wenn jemand einen weißen Bildschirm meldet:** zuerst prüfen, ob es am Server liegt.

```bash
curl -sI https://geodb.geolab.soz.uni-bielefeld.de/$(curl -s https://geodb.geolab.soz.uni-bielefeld.de/ \
  | grep -o 'assets/index-[A-Za-z0-9_-]*\.js') | grep -i content-type
```

Dort muss `text/javascript` stehen. Steht dort `text/html`, ist es der oben beschriebene Fehler.
Steht dort das Richtige, hat der Browser noch eine vergiftete Datei aus der Zeit davor im Speicher:
das lässt sich nur dort beheben, mit einem harten Neuladen (Strg+Umschalt+R, auf dem Mac
Cmd+Umschalt+R) oder über „Websitedaten löschen". Einmal genügt.

## Routine 4: eine Seite antwortet nicht

```bash
ssh vm "systemctl status geolab-inkar geolab-soep caddy --no-pager | head -30"
ssh vm "sudo systemctl restart geolab-inkar"     # GeoDB, Port 18002
ssh vm "sudo systemctl restart geolab-soep"      # SOEP, Port 18001
ssh vm "sudo journalctl -u geolab-soep --since '-1h' --no-pager | tail -40"
```

Nach einem Neustart braucht ein Dienst ein bis zwei Minuten, bis Einbettungen und Modell geladen
sind. Vorher antwortet er mit „Connection refused", und das ist normal.

## Routine 5: das Zertifikat

Beide Seiten benutzen ein Wildcard-Zertifikat für `*.geolab.soz.uni-bielefeld.de`, das von außen
nach `/etc/ssl/geolab.soz.uni-bielefeld.de/` gelegt wird. **Caddy liest diese Datei nur beim
Start.** Am 2026-08-06 wurde sie erneuert, Caddy lief weiter mit dem alten Zertifikat und hätte am
2026-09-06 ein abgelaufenes ausgeliefert: beide Seiten wären im Browser blockiert worden, an einem
Sonntag. Seitdem lädt `caddy-cert-reload.path` Caddy bei jeder Änderung der Datei neu, und der
Prüflauf vergleicht zusätzlich wöchentlich beide Zertifikate und lädt selbst nach.

Von Hand prüfen:

```bash
echo | openssl s_client -connect geodb.geolab.soz.uni-bielefeld.de:443 \
  -servername geodb.geolab.soz.uni-bielefeld.de 2>/dev/null | openssl x509 -noout -dates
ssh vm "sudo openssl x509 -noout -dates -in /etc/ssl/geolab.soz.uni-bielefeld.de/fullchain.cer"
ssh vm "sudo systemctl reload caddy"    # wenn das ausgelieferte älter ist als die Datei
```

## Symptom und Griff

| Symptom | Was zu tun ist |
|---|---|
| Seite lädt nicht | Routine 4 |
| Seite lädt, Suche liefert nichts | `ssh vm "sudo systemctl restart geolab-inkar geolab-soep"`, dann zwei Minuten warten |
| Browser warnt vor dem Zertifikat | Routine 5 |
| Ein Link im Finder führt ins Leere | Routine 2 |
| Bericht seit Wochen unverändert | `ssh vm "crontab -l"`, muss `run_health.sh` enthalten |
| Beim Einloggen kein Hinweis, aber Zweifel | `rm ~/.cache/geolab_health.msg && bash ~/kwandel/bin/geolab_alarm.sh` |
| Prüflauf meldet „Browser fehlt" | `bash scripts/install_health_check.sh` erneut laufen lassen |
| Auf lovelace fehlt plötzlich ein Werkzeug | `bash ~/kwandel/setup/bootstrap.sh` (der Pod hat sein Dateisystem geleert) |

## Nicht anfassen

- **Zugangsdaten** liegen in `~/.config/secrets/` und `~/kwandel/.config/secrets/`. Skripte lesen
  sie selbst. Nicht öffnen, nicht ausgeben, nicht in ein Repo legen, nicht in einen Chat kopieren.
- **In `/opt/geolab/` nichts von Hand bearbeiten.** Was dort liegt, wird ausgeliefert und beim
  nächsten Neuaufbau überschrieben. Änderungen gehören ins Repo auf lovelace.
- **Keine Forschungsdaten in die Repos.** Sie enthalten Quelltext, keine Daten und keine Modelle.
- **RegioPress-Volltexte** (aus dem Genios-Bestand) dürfen nicht öffentlich werden. Sie haben mit
  den Findern nichts zu tun, liegen aber auf derselben Maschine; die Regel gilt trotzdem.
- **INKAR/BBSR: sparsam bleiben.** Zwischen dem Projekt und dem BBSR besteht eine eigene
  Vereinbarung, deren Reichweite offen ist. Konstantin hat am 2026-09-06 entschieden, die
  Tiefenlinks trotzdem zu bauen, weil eine Klärung Monate dauern kann. Was daraus folgt: keine
  Serienabrufe gegen die Anwendung, kein Abgrasen, und die gespeicherten Abfragen entstehen nur
  einzeln beim ersten Klick (siehe unten). Lesen der öffentlichen Kataloge und Geodienste ist
  ohnehin unbedenklich.

## Die INKAR-Tiefenlinks

INKAR kennt keine Adresse für einen einzelnen Indikator. Das Einzige, was seine Adresszeile
transportiert, ist die Kennung einer **auf dem BBSR-Server gespeicherten Abfrage**. Deshalb zeigen
unsere INKAR-Treffer auf `geodb.geolab.soz.uni-bielefeld.de/api/inkar/open/<M_ID>`. Dieser Punkt
legt die Abfrage beim **ersten** Klick an, merkt sich die Kennung und leitet danach immer dorthin
weiter. Für Indikatoren, die niemand öffnet, entsteht beim BBSR nichts.

- Anlage und Ablage: `backend/app/services/inkar_permalink.py`, Ablage
  `/opt/geolab/app/destatis-rag/soep_metadata_output/inkar_permalinks.json`.
- Zuordnung der Kennungen: `data_sources/22-inkar/raw/wizard_katalog.json`, erzeugt von
  `scripts/fetch_inkar_wizard_catalogue.py` (nach einer neuen INKAR-Ausgabe neu erzeugen).
- Ansehen, prüfen, zurücknehmen, alles auf der VM:

```bash
python3 ~/health/repo/scripts/inkar_permalinks_admin.py --list
python3 ~/health/repo/scripts/inkar_permalinks_admin.py --check 5
python3 ~/health/repo/scripts/inkar_permalinks_admin.py --delete-all   # alles zurücknehmen
```

- **Abschalten** geht ohne neuen Index: `GEOLAB_INKAR_PERMALINKS=0` in der Dienstumgebung setzen und
  `sudo systemctl restart geolab-inkar`. Danach führt jeder INKAR-Treffer wieder auf inkar.de.
- Der Wochenbericht prüft eine Stichprobe der angelegten Abfragen (`inkar=ok(3)` in der
  Zusammenfassung). Fehlende sind kein Notfall: der Dienst legt sie beim nächsten Klick neu an.
- Falls sich das BBSR meldet: `--delete-all` entfernt jede von uns angelegte Abfrage, danach
  `GEOLAB_INKAR_PERMALINKS=0`. Beides zusammen dauert eine Minute.

## Was ein Skript nicht kann

Der Prüflauf erkennt, dass eine Adresse die Domain verlassen hat. Er kann nicht entscheiden, ob
das ein harmloser Umzug oder eine verfallene Domain in fremder Hand ist, ob ein eingestelltes
Portal aus dem Finder verschwinden soll oder als historischer Bestand bleibt, und ob eine neue
Adresse dieselben Daten zeigt wie die alte. Diese Urteile bleiben bei einem Menschen. Was
automatisiert ist, ist die Beobachtung und die Verkürzung der Reparatur auf wenige Schritte.

## Die monatliche Runde mit Claude

Wer Claude Code benutzt, muss Routine 1 und 2 nicht von Hand machen. In einer Sitzung im
Arbeitsbereich `~/kwandel` genügt

> monatliche Wartung der Finder

und der Skill `geolab-wartung` übernimmt: Bericht lesen, das mechanisch Eindeutige beheben
(umgezogene Adresse nach `SOURCE_FIXES`, unprüfbare Adresse mit Wiedervorlagedatum nach
`known_url_issues.json`), festschreiben, und die Urteilsfragen vorlegen. Er liefert nicht aus und
baut den Index nicht neu, weil beides eine bewusste Entscheidung ist.

**Das startet niemand von selbst.** Auf lovelace gibt es kein Claude-Programm auf der
Kommandozeile, also kann kein Zeitplan diese Runde anstoßen. Was automatisch geschieht, ist die
Erinnerung: `~/kwandel/bin/geolab_alarm.sh` vergleicht das Datum in
`output/last_maintenance.txt` mit heute und meldet beim Einloggen, wenn die Runde über 35 Tage
her ist. Der Skill schreibt das Datum am Ende neu.

## Für KI-Agenten

`CLAUDE.md` ist die technische Innenansicht dieses Repos, dieses Dokument die Bedienungsanleitung.
Wenn ein Prüflauf rot ist, gilt Routine 2: die Korrektur gehört nach `SOURCE_FIXES`, nicht in ein
neu erfundenes Verfahren und nicht von Hand in die erzeugte Registry.
