#!/usr/bin/env python3
"""Wöchentlicher Zustandsbericht für die beiden GeoLAB-Metadatenfinder.

Läuft auf der geolab-VM, weil das hier die einzige Maschine mit einem Zeitplan ist, der einen
Neustart übersteht: lovelace ist ein Kubernetes-Pod ohne benutzereigenes systemd, und /etc wird
beim Neubau geleert. Eine GPU braucht dieser Lauf nicht.

Geprüft wird in der Reihenfolge, in der die Dinge tatsächlich verrotten:

  quellen    die Einstiegsseiten aus der Registry, im echten Browser, mit Ziel nach Weiterleitung
             und Hinweis, wenn die Adresse die ursprüngliche Domain verlassen hat
  links      eine je Woche wandernde Stichprobe der Tiefenlinks, mit Shell-Erkennung
  dienst     beide APIs beantworten eine echte Frage mit mehr als null Treffern
  alter      wie alt der Index ist
  zertifikat ob das Zertifikat auf der Platte auch das ist, das der Server ausliefert
  maschine   Plattenplatz und letzter erfolgreicher Auslagerungslauf

Selbstheilung ist absichtlich klein gehalten: ein tot liegender Dienst wird einmal neu gestartet,
und Caddy wird neu geladen, wenn es ein älteres Zertifikat ausliefert als das, das auf der Platte
liegt. Beides wird protokolliert. Alles andere wird nur berichtet. Dass eine verfallene Domain
inzwischen einer Firma gehört und die Quellenkarte deshalb verschwinden muss, ist ein Urteil, und
ein Skript, das so etwas selbst entscheidet, würde die Fäulnis verdecken statt sie zu zeigen.

    python3 scripts/health_check.py              # vollständig
    python3 scripts/health_check.py --quick      # ohne Browser und ohne Linkstichprobe
    python3 scripts/health_check.py --no-heal    # nichts neu starten, nur berichten

Ergebnis: state/latest.json (vollständig) und eine Zeile in logs/health.log (Verlauf).
Rückgabewert: 0 alles grün, 1 gelb (etwas beobachten), 2 rot (etwas ist kaputt).
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "state"
LOGS = ROOT / "logs"
METADATA_DIR = Path("/opt/geolab/app/destatis-rag/soep_metadata_output")
KNOWN_ISSUES = ROOT / "data_sources" / "registry" / "known_url_issues.json"

FINDERS = [
    {"key": "inkar", "unit": "geolab-inkar", "port": 18002,
     "host": "geodb.geolab.soz.uni-bielefeld.de", "frage": "Arbeitslosenquote auf Kreisebene"},
    {"key": "soep", "unit": "geolab-soep", "port": 18001,
     "host": "soep-faiss.geolab.soz.uni-bielefeld.de", "frage": "Lebenszufriedenheit"},
]

# Schwellen. Absichtlich großzügig: ein Bericht, der jede Woche gelb ist, wird nicht gelesen.
LINK_OK_WARN = 0.90        # Anteil auflösbarer Links, darunter gelb
LINK_OK_BAD = 0.75         # darunter rot
INDEX_AGE_WARN = 200       # Tage
INDEX_AGE_BAD = 400
DISK_WARN = 90             # Prozent belegt
DISK_BAD = 95
CERT_WARN = 21             # Tage Restlaufzeit (Caddy erneuert selbst; darunter ist die Erneuerung defekt)
CERT_BAD = 7
BACKUP_WARN = 4            # Tage seit dem letzten erfolgreichen Auslagerungslauf
BACKUP_BAD = 10


def worse(a: str, b: str) -> str:
    order = {"ok": 0, "warn": 1, "bad": 2}
    return a if order[a] >= order[b] else b


def run(cmd: list[str], timeout: int = 900) -> tuple[int, str]:
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=ROOT)
        return done.returncode, (done.stdout or "") + (done.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, f"Zeitüberschreitung nach {timeout}s"
    except OSError as exc:
        return 127, str(exc)


# ---------------------------------------------------------------- Quellenadressen (Browser)

def known_issues() -> dict[str, dict]:
    """Adressen, die schon bekannt und begründet auffällig sind.

    Ohne diese Liste wäre der Bericht dauerhaft rot, und ein Bericht, der immer rot ist, wird
    nicht gelesen. Sie enthält nur, was von außen nicht prüfbar ist, etwa eine Seite mit
    Bot-Schutz. Eine wirklich umgezogene Adresse wird in SOURCE_FIXES korrigiert.
    """
    if not KNOWN_ISSUES.exists():
        return {}
    data = json.loads(KNOWN_ISSUES.read_text(encoding="utf-8"))
    return {row["slug"]: row for row in data.get("issues", [])}


def check_sources(python: str) -> dict:
    """Die Einstiegsseiten aus der Registry, im echten Browser.

    Der Browser ist keine Bequemlichkeit: GENESIS-Online und der Deutschlandatlas weisen
    Skriptanfragen ab und würden von einer einfachen Statusprüfung als tot gemeldet.
    """
    out = STATE / "sources.json"
    code, log = run([python, "scripts/check_source_urls.py", "--json-out", str(out)], timeout=1800)
    if code != 0 or not out.exists():
        return {"verdict": "warn", "detail": "Prüfung nicht gelaufen (Browser fehlt?)",
                "log": log.strip()[-400:]}
    data = json.loads(out.read_text(encoding="utf-8"))
    rows = data.get("results", [])
    bekannt = known_issues()
    tot, umgezogen, anerkannt, faellig = [], [], [], []
    heute = date.today().isoformat()
    for row in rows:
        slug, status = row["slug"], row.get("status")
        auffaellig = bool(row.get("moved")) or not (isinstance(status, int) and 200 <= status < 300)
        if not auffaellig:
            continue
        if slug in bekannt:
            anerkannt.append(f"{slug} ({bekannt[slug].get('grund', '')[:60]})")
            if str(bekannt[slug].get("wiedervorlage", "9999")) <= heute:
                faellig.append(f"{slug}: Wiedervorlage seit {bekannt[slug]['wiedervorlage']}")
            continue
        if row.get("moved"):
            # Der schlimmere Fall: die Antwort ist 200, aber die Adresse hat die Domain verlassen.
            # So fiel breitband-monitor.de auf, das nach dem Verfall auf eine Firmenseite umleitete.
            umgezogen.append(f"{slug} -> {(row.get('final_url') or '')[:80]}")
        else:
            tot.append(f"{slug}: {status or (row.get('error') or '').splitlines()[0][:50]}")
    verdict = "bad" if (tot or umgezogen) else "warn" if faellig else "ok"
    return {"verdict": verdict, "geprueft": len(rows), "tot": tot, "domain_verlassen": umgezogen,
            "anerkannt": anerkannt, "wiedervorlage_faellig": faellig}


# ---------------------------------------------------------------- Tiefenlinks (Stichprobe)

def check_links(python: str, per_source: int) -> dict:
    """Eine je Woche wandernde Stichprobe der Tiefenlinks.

    Der Startwert ist die Kalenderwoche, damit über die Wochen andere Datensätze an die Reihe
    kommen und der Bestand mit der Zeit durchläuft, statt immer dieselben Zeilen zu prüfen.
    """
    year, week, _ = date.today().isocalendar()
    seed = year * 100 + week
    out = STATE / "links.json"
    code, log = run([python, "scripts/check_geodb_links.py", "--per-source", str(per_source),
                     "--seed", str(seed), "--json-out", str(out)], timeout=1800)
    if code != 0 or not out.exists():
        return {"verdict": "warn", "detail": "Prüfung nicht gelaufen", "log": log.strip()[-400:]}
    results = json.loads(out.read_text(encoding="utf-8")).get("results", [])
    if not results:
        return {"verdict": "warn", "detail": "keine Stichprobe"}
    ok = sum(1 for r in results if r["verdict"] == "ok")
    shell = sum(1 for r in results if r["verdict"] == "shell")
    broken = [r for r in results if r["verdict"] not in ("ok", "shell")]
    # 'shell' heißt: die Seite ist eine im Browser aufgebaute Anwendung und von außen nicht prüfbar,
    # nicht dass der Link kaputt ist. Solche Zeilen gehen nicht in die Quote ein.
    pruefbar = len(results) - shell
    share = ok / pruefbar if pruefbar else 1.0
    verdict = "ok"
    if share < LINK_OK_BAD:
        verdict = "bad"
    elif share < LINK_OK_WARN:
        verdict = "warn"
    je_quelle: dict[str, int] = {}
    for row in broken:
        je_quelle[row["source_key"]] = je_quelle.get(row["source_key"], 0) + 1
    return {"verdict": verdict, "seed": seed, "geprueft": len(results), "ok": ok,
            "nicht_pruefbar": shell, "quote": round(share, 3),
            "kaputt": len(broken), "kaputt_je_quelle": je_quelle,
            "beispiele": [f"{r['verdict']} [{r['source_key']}] {r['url'][:110]}" for r in broken[:8]]}


# ---------------------------------------------------------------- Dienste

def ask_finder(port: int, frage: str, timeout: int = 90) -> tuple[bool, str, int]:
    body = json.dumps({"question": frage, "top_k": 3}).encode("utf-8")
    request = urllib.request.Request(f"http://127.0.0.1:{port}/api/soep/advice", data=body,
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError) as exc:
        return False, f"nicht erreichbar ({str(getattr(exc, 'reason', exc))[:60]})", 0
    hits = data.get("recommended_variables")
    hits = len(hits) if isinstance(hits, list) else int(hits or 0)
    if hits <= 0:
        return False, "antwortet, liefert aber null Treffer", 0
    return True, "ok", hits


def check_services(heal: bool) -> dict:
    """Eine echte Frage, nicht /health.

    /health sagt nur, dass der Prozess läuft. Ein Dienst mit fehlendem Index antwortet dort
    weiter mit ok und liefert dabei null Treffer, und genau dieser Fall ist der stille Ausfall,
    der ohne echte Frage niemandem auffällt.
    """
    detail, verdict, heilungen = {}, "ok", []
    for finder in FINDERS:
        good, message, hits = ask_finder(finder["port"], finder["frage"])
        if not good and heal:
            # Die einzige Selbstheilung, die ein Skript verantworten kann.
            subprocess.run(["sudo", "-n", "systemctl", "restart", finder["unit"]],
                           capture_output=True, text=True, timeout=120)
            # Zwischen den Versuchen muss gewartet werden. Ein noch nicht lauschender Dienst
            # weist die Verbindung sofort ab, sodass zwanzig Versuche ohne Pause in einer Sekunde
            # verbraucht wären und der Neustart als gescheitert gälte, obwohl der Dienst nur die
            # Einbettungen und das Modell lädt. Das dauert ein bis zwei Minuten.
            for _ in range(20):
                time.sleep(15)
                good, message, hits = ask_finder(finder["port"], finder["frage"], timeout=45)
                if good:
                    break
            heilungen.append(f"{finder['unit']} neu gestartet, danach: {message}")
        detail[finder["key"]] = {"ok": good, "meldung": message, "treffer": hits}
        if not good:
            verdict = "bad"
    return {"verdict": verdict, "finder": detail, "selbstheilung": heilungen}


# ---------------------------------------------------------------- Alter, Maschine

def check_freshness() -> dict:
    info = METADATA_DIR / "geodb_build_info.json"
    if not info.exists():
        return {"verdict": "warn", "detail": f"{info} fehlt"}
    built = json.loads(info.read_text(encoding="utf-8"))
    stamp = str(built.get("built") or built.get("built_at") or built.get("as_of") or "")
    match = re.search(r"\d{4}-\d{2}-\d{2}", stamp)
    if not match:
        return {"verdict": "warn", "detail": f"kein Datum in {info.name}: {stamp[:40]}"}
    age = (date.today() - date.fromisoformat(match.group(0))).days
    verdict = "bad" if age > INDEX_AGE_BAD else "warn" if age > INDEX_AGE_WARN else "ok"
    return {"verdict": verdict, "stand": match.group(0), "alter_tage": age,
            "datensaetze": built.get("records"), "quellen": built.get("sources")}


CERT_FILE = Path("/etc/ssl/geolab.soz.uni-bielefeld.de/fullchain.cer")


def _rest_tage(not_after: datetime) -> int:
    return (not_after - datetime.now(timezone.utc)).days


def served_cert(host: str) -> int | str:
    """Restlaufzeit des Zertifikats, das der Server gerade ausliefert."""
    context = ssl.create_default_context()
    try:
        with socket.create_connection((host, 443), timeout=15) as raw:
            with context.wrap_socket(raw, server_hostname=host) as tls:
                not_after = tls.getpeercert()["notAfter"]
    except (OSError, ssl.SSLError, KeyError, TypeError) as exc:
        return f"nicht prüfbar ({str(exc)[:40]})"
    return _rest_tage(datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc))


def file_cert() -> int | str:
    """Restlaufzeit des Zertifikats, das auf der Platte liegt."""
    if not CERT_FILE.exists():
        return "keine Datei"
    code, out = run(["openssl", "x509", "-noout", "-enddate", "-in", str(CERT_FILE)], timeout=30)
    match = re.search(r"notAfter=(.+)", out)
    if code != 0 or not match:
        return f"nicht lesbar ({out.strip()[:40]})"
    return _rest_tage(datetime.strptime(match.group(1).strip(), "%b %d %H:%M:%S %Y %Z")
                      .replace(tzinfo=timezone.utc))


def check_certificate(heal: bool) -> dict:
    """Wird das Zertifikat auf der Platte auch ausgeliefert?

    Am 2026-09-03 lief hier genau das schief: die Datei war am 6. August erneuert worden, Caddy
    liest sie aber nur beim Start, also lieferte es weiter das alte Zertifikat aus, das drei Tage
    später abgelaufen wäre. Beide Finder wären im Browser blockiert worden, und der Ablauf wäre
    auf einen Sonntag gefallen. Seitdem lädt eine systemd-Path-Einheit Caddy beim Austausch neu;
    diese Prüfung ist das Netz darunter und lädt selbst nach, wenn die Einheit einmal fehlt.
    """
    auf_platte = file_cert()
    ausgeliefert = {finder["host"]: served_cert(finder["host"]) for finder in FINDERS}
    heilung = []
    veraltet = [host for host, tage in ausgeliefert.items()
                if isinstance(tage, int) and isinstance(auf_platte, int) and auf_platte > tage + 1]
    if veraltet and heal:
        subprocess.run(["sudo", "-n", "systemctl", "reload", "caddy"],
                       capture_output=True, text=True, timeout=120)
        ausgeliefert = {finder["host"]: served_cert(finder["host"]) for finder in FINDERS}
        heilung.append(f"Caddy neu geladen, weil {', '.join(veraltet)} ein älteres Zertifikat "
                       f"auslieferte als die Datei auf der Platte")

    verdict = "ok"
    for tage in ausgeliefert.values():
        if not isinstance(tage, int):
            verdict = worse(verdict, "warn")
        elif tage <= CERT_BAD:
            verdict = worse(verdict, "bad")
        elif tage <= CERT_WARN:
            verdict = worse(verdict, "warn")
    if veraltet and not heal:
        verdict = worse(verdict, "bad")
    return {"verdict": verdict, "ausgeliefert_tage": ausgeliefert, "auf_platte_tage": auf_platte,
            "path_einheit": systemd_path_active(), "selbstheilung": heilung}


def systemd_path_active() -> str:
    code, out = run(["systemctl", "is-active", "caddy-cert-reload.path"], timeout=30)
    return out.strip() or f"unbekannt ({code})"


def check_host() -> dict:
    verdict = "ok"
    usage = shutil.disk_usage("/")
    percent = round(usage.used / usage.total * 100)
    if percent >= DISK_BAD:
        verdict = "bad"
    elif percent >= DISK_WARN:
        verdict = "warn"

    backup = {"detail": "kein Protokoll gefunden"}
    log = Path.home() / "backup_sync" / "logs" / "sync_geolab.log"
    if log.exists():
        hits = [line for line in log.read_text(errors="replace").splitlines() if "done ok" in line]
        if hits:
            stamp = re.search(r"\d{4}-\d{2}-\d{2}", hits[-1])
            if stamp:
                age = (date.today() - date.fromisoformat(stamp.group(0))).days
                backup = {"letzter_erfolg": stamp.group(0), "alter_tage": age}
                if age > BACKUP_BAD:
                    verdict = worse(verdict, "bad")
                elif age > BACKUP_WARN:
                    verdict = worse(verdict, "warn")
    return {"verdict": verdict, "platte_prozent": percent,
            "platte_frei_gb": round(usage.free / 1e9, 1), "auslagerung": backup}


# ---------------------------------------------------------------- Bericht

def check_frontends() -> dict:
    """Kommt das Bündel, auf das die Seite verweist, auch wirklich als JavaScript zurück?

    Am 2026-09-05 gemeldet als "manchmal weißer Bildschirm, in verschiedenen Browsern". Ursache
    war nicht der Browser: `try_files` schrieb jeden unbekannten Pfad auf `index.html` um, und die
    Kopfzeile für Bündel hing allein am angefragten Pfad. Eine fehlende Bündeldatei kam deshalb
    mit HTTP 200, `Content-Type: text/html` und `Cache-Control: immutable` für ein Jahr zurück.
    Der Browser legte das HTML dauerhaft unter der JS-Adresse ab, das Programm startete nie, und
    die Seite blieb weiß. Beides wird hier geprüft, weil beides von außen unsichtbar war und für
    einen Besucher wie ein kaputter Rechner aussieht.
    """
    detail, verdict = {}, "ok"
    for finder in FINDERS:
        eintrag = {}
        try:
            dok = urllib.request.urlopen(f"https://{finder['host']}/", timeout=30)
            html = dok.read().decode("utf-8", "replace")
            eintrag["dokument_cache"] = dok.headers.get("Cache-Control", "")
            treffer = re.search(r"/assets/(index-[A-Za-z0-9_-]+\.js)", html)
            if not treffer:
                eintrag["fehler"] = "im Dokument steht kein Bündel"
                verdict = worse(verdict, "bad")
            else:
                name = treffer.group(1)
                eintrag["bündel"] = name
                antwort = urllib.request.urlopen(f"https://{finder['host']}/assets/{name}", timeout=30)
                typ = antwort.headers.get("Content-Type", "")
                eintrag["typ"] = typ
                if "javascript" not in typ:
                    eintrag["fehler"] = f"das Bündel kommt als {typ} zurück, nicht als JavaScript"
                    verdict = worse(verdict, "bad")
            # Und die andere Richtung: ein Name, den es nicht gibt, muss 404 sagen.
            try:
                urllib.request.urlopen(f"https://{finder['host']}/assets/index-GIBTESNICHT.js", timeout=30)
                eintrag["fehlende_datei"] = "200 statt 404, die Umschreibung auf index.html ist zurück"
                verdict = worse(verdict, "bad")
            except urllib.error.HTTPError as fehler:
                eintrag["fehlende_datei"] = f"{fehler.code}"
                if fehler.code != 404:
                    verdict = worse(verdict, "warn")
        except Exception as fehler:  # noqa: BLE001
            eintrag["fehler"] = f"{type(fehler).__name__}: {fehler}"
            verdict = worse(verdict, "bad")
        detail[finder["key"]] = eintrag
    return {"verdict": verdict, "detail": detail}


def check_inkar_links() -> dict:
    """Halten die INKAR-Tiefenlinks noch?

    Diese Links hängen an Abfragen, die auf dem Server des BBSR liegen (siehe
    backend/app/services/inkar_permalink.py). Räumt das BBSR dort auf, zeigen unsere Links ins
    Leere, und niemand würde es merken: die Weiterleitung antwortet weiter, nur die Zieltabelle
    ist dann weg. Deshalb wird eine Stichprobe wirklich abgerufen. Fehlende Abfragen sind kein
    Notfall, der Dienst legt sie beim nächsten Klick neu an, aber gelb ist es allemal.
    """
    ablage = Path("/opt/geolab/app/destatis-rag/soep_metadata_output/inkar_permalinks.json")
    if not ablage.exists():
        return {"verdict": "ok", "detail": "noch keine Tiefenlinks angelegt"}
    try:
        cache = json.loads(ablage.read_text(encoding="utf-8"))
    except Exception as fehler:  # noqa: BLE001
        return {"verdict": "warn", "detail": f"Ablage unlesbar: {fehler}"}
    links = cache.get("links") or {}
    if not links:
        return {"verdict": "ok", "detail": "noch keine Tiefenlinks angelegt"}
    stichprobe = list(links.items())[:5]
    gut, weg = 0, []
    for m_id, eintrag in stichprobe:
        try:
            antwort = urllib.request.urlopen(
                urllib.request.Request(f"https://www.inkar.de/Main/GetUserQuery/{eintrag['id']}",
                                       headers={"User-Agent": "geolab-healthcheck"}),
                timeout=30, context=ssl._create_unverified_context()).read().decode("utf-8", "replace")
            if "IndicatorCollection" in antwort:
                gut += 1
            else:
                weg.append(m_id)
        except Exception:  # noqa: BLE001
            weg.append(m_id)
    return {"verdict": "ok" if not weg else "warn",
            "angelegt": len(links), "geprüft": len(stichprobe), "vorhanden": gut,
            "verschwunden": weg}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--quick", action="store_true", help="ohne Browser und Linkstichprobe")
    parser.add_argument("--no-heal", action="store_true", help="keinen Dienst neu starten")
    parser.add_argument("--per-source", type=int, default=20,
                        help="Tiefenlinks je Quelle in der Stichprobe (Standard 20, macht ~420)")
    parser.add_argument("--python", default=sys.executable,
                        help="Python mit playwright für die Adressprüfung")
    args = parser.parse_args()

    STATE.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)

    report = {"gelaufen": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "modus": "quick" if args.quick else "vollständig"}
    report["dienst"] = check_services(heal=not args.no_heal)
    report["oberfläche"] = check_frontends()
    report["inkar_links"] = check_inkar_links()
    report["alter"] = check_freshness()
    report["zertifikat"] = check_certificate(heal=not args.no_heal)
    report["maschine"] = check_host()
    if args.quick:
        report["quellen"] = {"verdict": "ok", "detail": "übersprungen (--quick)"}
        report["links"] = {"verdict": "ok", "detail": "übersprungen (--quick)"}
    else:
        report["quellen"] = check_sources(args.python)
        report["links"] = check_links(sys.executable, args.per_source)

    gesamt = "ok"
    for key in ("dienst", "oberfläche", "inkar_links", "quellen", "links", "alter", "zertifikat", "maschine"):
        gesamt = worse(gesamt, report[key].get("verdict", "ok"))

    # Eine Reparatur darf den Anlass nicht verschlucken. Ein Dienst, der jede Woche neu gestartet
    # werden muss, ist kaputt, auch wenn jeder Neustart gelingt, und ein grüner Bericht würde
    # genau das verbergen. Nach einer Selbstheilung ist der Bericht deshalb gelb.
    geheilt = [zeile for key in ("dienst", "zertifikat")
               for zeile in report[key].get("selbstheilung", [])]
    if geheilt:
        gesamt = worse(gesamt, "warn")
    report["selbstheilung"] = geheilt
    report["gesamt"] = gesamt

    (STATE / "latest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                       encoding="utf-8")
    zeile = (f"[{report['gelaufen']}] {gesamt.upper():<4} "
             f"dienst={report['dienst']['verdict']} "
             f"oberfläche={report['oberfläche']['verdict']} "
             f"inkar={report['inkar_links']['verdict']}"
             f"({report['inkar_links'].get('angelegt', 0)}) "
             f"quellen={report['quellen']['verdict']} "
             f"links={report['links']['verdict']}"
             f"({report['links'].get('quote', '-')}) "
             f"alter={report['alter'].get('alter_tage', '?')}d "
             f"zert={report['zertifikat']['verdict']} "
             f"maschine={report['maschine']['verdict']}"
             + (f" | geheilt: {'; '.join(geheilt)}" if geheilt else ""))
    with (LOGS / "health.log").open("a", encoding="utf-8") as handle:
        handle.write(zeile + "\n")
    print(zeile)
    for key in ("dienst", "oberfläche", "inkar_links", "quellen", "links", "alter", "zertifikat", "maschine"):
        if report[key].get("verdict", "ok") != "ok":
            print(f"  {key}: {json.dumps(report[key], ensure_ascii=False)[:600]}")
    return {"ok": 0, "warn": 1, "bad": 2}[gesamt]


if __name__ == "__main__":
    raise SystemExit(main())
