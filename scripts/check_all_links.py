#!/usr/bin/env python3
"""Jeden auswärtigen Verweis des GeoLAB-Bestandes einmal anfassen und festhalten, was antwortet.

`check_geodb_links.py` zieht eine Stichprobe je Quelle und beantwortet damit die Frage, ob eine
Quelle grundsätzlich erreichbar ist. Diese Prüfung beantwortet die andere Frage: welcher einzelne
Verweis ins Leere zeigt. Sie holt deshalb jede verschiedene Adresse aus allen vier Beständen und
aus den fertig gerenderten Seiten:

  destatis-rag/soep_metadata_output/geodb_metadata.json      der Index hinter dem GeoDB-Finder
  destatis-rag/soep_metadata_output/inkar_metadata_2025.json  INKAR, eigener Bestand
  geolab_regiohub/tools/measure-register/register.json        das Merkmalsregister
  geolab_regiohub/tools/link-builder/catalogue.json           der Katalog des Planers
  geolab_regiohub/_site/**.html                               die veröffentlichten Seiten

Urteile, dieselben wie in der Stichprobenprüfung, plus zwei:

  ok             HTTP 2xx, und die Seite ist größer als die bekannte Fehlseite des Hosts
  shell          HTTP 2xx, aber so groß wie die Antwort auf einen absichtlich falschen Code:
                 ein im Browser aufgebautes Portal, hier also nicht nachweisbar
  http-<code>    der Server hat mit 4xx/5xx geantwortet
  unreachable    DNS, TLS, Zeitüberschreitung
  uebersprungen  nicht angefasst, weil eine Absprache es verbietet (INKAR/BBSR)

Höflichkeit: je Host höchstens zwei gleichzeitige Anfragen und ein Abstand dazwischen. Das ist
kein Feinschliff, sondern die Bedingung, unter der so ein Lauf überhaupt zulässig ist.

  python3 scripts/check_all_links.py                       # alles
  python3 scripts/check_all_links.py --host statistik.arbeitsagentur.de
  python3 scripts/check_all_links.py --only-geodb --json-out output/link_health_full.json
"""
from __future__ import annotations

import argparse, collections, html, json, pathlib, re, threading, time, urllib.parse
from concurrent.futures import ThreadPoolExecutor

import sys
HIER = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HIER))
from check_geodb_links import fetch_size, BOGUS_PROBES          # eine Holfunktion, nicht zwei

REPO = HIER.parent
SITE = REPO.parent / "geolab_regiohub"

# INKAR und das BBSR: keine Reihe selbsttätiger Anfragen, so abgesprochen. Die Adressen werden
# gesammelt und ausgewiesen, aber nicht geholt.
#
# Der vierte Eintrag ist der wichtige und er hat am 13.09.2026 gefehlt. Unsere INKAR-Verweise
# zeigen nicht auf inkar.de, sondern auf unseren eigenen Weiterleitungspunkt, und der LEGT BEIM
# ERSTEN ÖFFNEN EINE ABFRAGE AUF DEM BBSR-SERVER AN. Ein Prüflauf über diese Adressen schreibt
# also in fremde Systeme: 353 Abfragen sind so entstanden und mussten wieder gelöscht werden.
# Eine Sperrliste nach Hostnamen reicht hier nicht, gesperrt gehört jeder Weg, der dort endet.
NICHT_ANFASSEN = ("inkar.de", "bbsr.bund.de", "bbsr-geodienste.de", "/api/inkar/open/")

# Hosts, die auf JEDE Adresse dieselbe Hülle zurückgeben, weil die Seite erst im Browser
# entsteht. Gemessen am 13.09.2026, nicht vermutet: 543 Zensus-Adressen ergaben genau EINE
# Antwortgröße (1728 B), 519 Adressen der Bundes-GENESIS genau eine (2506 B), 233 des
# Regionalatlas genau eine (23902 B), und jede davon ist die Antwort auf einen absichtlich
# falschen Code. Zum Vergleich: die Regionalstatistik lieferte auf 542 Adressen 511
# verschiedene Größen, dort ist jede Anfrage eine echte Auskunft.
#
# Für diese Hosts prüft der Lauf deshalb nur noch eine Stichprobe. Alles weitere wäre keine
# Prüfung, sondern Last auf fremden Servern für eine Antwort, die vorher feststeht. Wer diese
# Verweise wirklich nachweisen will, braucht einen Browser, wie es check_ioer_links.py für den
# IÖR-Monitor tut.
NUR_STICHPROBE = {"ergebnisse.zensus2022.de": 500,
                  "www-genesis.destatis.de": 500,
                  "regionalatlas.statistikportal.de": 250}

ABSTAND = 0.35          # Sekunden zwischen zwei Anfragen an denselben Host
JE_HOST = 2             # gleichzeitige Anfragen an denselben Host


class Schleuse:
    """Hält je Host den letzten Anfragezeitpunkt und die Zahl der Läufer."""
    def __init__(self):
        self._sperre = collections.defaultdict(threading.Semaphore)
        self._zuletzt = collections.defaultdict(float)
        self._buch = threading.Lock()
        self._sem = {}

    def sem(self, host):
        with self._buch:
            if host not in self._sem:
                self._sem[host] = threading.Semaphore(JE_HOST)
            return self._sem[host]

    def hole(self, url):
        host = urllib.parse.urlsplit(url).netloc
        s = self.sem(host)
        with s:
            with self._buch:
                warte = ABSTAND - (time.time() - self._zuletzt[host])
            if warte > 0:
                time.sleep(warte)
            with self._buch:
                self._zuletzt[host] = time.time()
            return fetch_size(url)


def aus_json(pfad, felder=None):
    """Alle Zeichenketten, die wie eine Adresse aussehen, egal wie tief sie liegen."""
    gefunden = set()
    def geh(x, schluessel=None):
        if isinstance(x, str):
            if x.startswith("http"):
                if felder is None or schluessel in felder:
                    gefunden.add(x.strip())
        elif isinstance(x, dict):
            for k, v in x.items(): geh(v, k)
        elif isinstance(x, list):
            for v in x: geh(v, schluessel)
    if pfad.exists():
        geh(json.loads(pfad.read_text(encoding="utf-8")))
    return gefunden


HREF = re.compile(r'href="(https?://[^"]+)"')


def aus_seiten(wurzel):
    """Aus fertigem HTML, und deshalb mit Entitäten zurückübersetzt.

    In einer Seite steht `&amp;` da, wo die Adresse ein `&` hat: so gehört sich das, und genau
    so muss man es wieder auflösen. Ohne das schickt der Prüfer eine Adresse los, die es nie
    gab, bekommt vom gbe-bund eine 500 zurück und meldet einen kaputten Verweis, der in
    Wahrheit tadellos funktioniert."""
    gefunden = set()
    for f in wurzel.rglob("*.html"):
        for u in HREF.findall(f.read_text(encoding="utf-8", errors="ignore")):
            gefunden.add(html.unescape(u.split("#")[0].rstrip(")").strip()))
    return gefunden


def sammle():
    q = {}
    def dazu(name, menge):
        for u in menge: q.setdefault(u, set()).add(name)
    dazu("geodb", aus_json(REPO / "soep_metadata_output" / "geodb_metadata.json"))
    dazu("inkar", aus_json(REPO / "soep_metadata_output" / "inkar_metadata_2025.json"))
    dazu("register", aus_json(SITE / "tools" / "measure-register" / "register.json"))
    dazu("planer", aus_json(SITE / "tools" / "link-builder" / "catalogue.json"))
    if (SITE / "_site").exists():
        dazu("seite", aus_seiten(SITE / "_site"))
    return q


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", default="", help="nur diesen Host prüfen")
    p.add_argument("--only-geodb", action="store_true")
    p.add_argument("--workers", type=int, default=24)
    p.add_argument("--neu", action="store_true", help="von vorn, Zwischenstand verwerfen")
    p.add_argument("--json-out", default=str(REPO / "output" / "link_health_full.json"))
    a = p.parse_args()

    quellen = sammle()
    if a.only_geodb:
        quellen = {u: s for u, s in quellen.items() if "geodb" in s}
    if a.host:
        quellen = {u: s for u, s in quellen.items() if urllib.parse.urlsplit(u).netloc == a.host}

    def verschraenkt(us):
        """Reihum je Host eine Adresse. Sortiert liegen alle Adressen eines Hosts beieinander,
        dann drängen sich alle Läufer an derselben Türschwelle und es laufen zwei statt
        vierundzwanzig. Die Höflichkeit je Host bleibt davon unberührt, sie steckt in der
        Schleuse."""
        nach_host = collections.defaultdict(list)
        for u in sorted(us):
            nach_host[urllib.parse.urlsplit(u).netloc].append(u)
        reihen, raus = list(nach_host.values()), []
        while reihen:
            for r in list(reihen):
                raus.append(r.pop(0))
                if not r: reihen.remove(r)
        return raus

    adressen = verschraenkt(quellen)
    uebersprungen = [u for u in adressen if any(h in u for h in NICHT_ANFASSEN)]
    zu_pruefen = [u for u in adressen if u not in set(uebersprungen)]
    gedeckelt = collections.Counter()
    behalten, gedeckelt_weg = [], collections.Counter()
    for u in zu_pruefen:
        h = urllib.parse.urlsplit(u).netloc
        grenze = NUR_STICHPROBE.get(h)
        if grenze is None:
            behalten.append(u); continue
        gedeckelt[h] += 1
        if gedeckelt[h] <= grenze:
            behalten.append(u)
        else:
            gedeckelt_weg[h] += 1
    zu_pruefen = behalten
    for h, n in gedeckelt_weg.most_common():
        print(f"  {h}: nur Stichprobe, {n} weitere Adressen nicht angefasst (immer dieselbe Hülle)")

    hosts = collections.Counter(urllib.parse.urlsplit(u).netloc for u in zu_pruefen)
    print(f"{len(adressen)} verschiedene Adressen, {len(zu_pruefen)} werden geholt, "
          f"{len(uebersprungen)} übersprungen (Absprache), {len(hosts)} Hosts")

    roh = pathlib.Path(a.json_out).with_name("link_health_roh.jsonl")
    schon = {}
    if roh.exists() and not a.neu:
        for zeile in roh.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(zeile)
                # Nur, was zur jetzigen Auswahl gehört: bei --host steht im Zwischenstand noch
                # alles von früheren Läufen, und der Bericht schlug sonst beim Zusammenbauen fehl.
                if e["url"] in quellen:
                    schon[e["url"]] = e
            except Exception:
                pass
        zu_pruefen = [u for u in zu_pruefen if u not in schon]
        print(f"  {len(schon)} schon geprüft, {len(zu_pruefen)} bleiben")

    schleuse = Schleuse()
    print("\nFehlseiten-Größen (Antwort auf einen absichtlich falschen Code):")
    with ThreadPoolExecutor(max_workers=6) as pool:
        shells = dict(zip(BOGUS_PROBES, pool.map(schleuse.hole, BOGUS_PROBES.values())))
    for k, v in shells.items():
        print(f"  {v!s:>10}  {k}")

    t0 = time.time()
    fertig = [0]
    sperre = threading.Lock()

    def eine(u):
        g = schleuse.hole(u)
        with sperre:
            with roh.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"url": u, "groesse": g}, ensure_ascii=False) + "\n")
            fertig[0] += 1
            if fertig[0] % 250 == 0:
                verstrichen = time.time() - t0
                print(f"  {fertig[0]}/{len(zu_pruefen)} nach {verstrichen/60:.1f} min", flush=True)
        return g

    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        groessen = list(pool.map(eine, zu_pruefen))

    ergebnis = []
    for u, g in list(zip(zu_pruefen, groessen)) + [(u, e["groesse"]) for u, e in schon.items()]:
        urteil = g if isinstance(g, str) else "ok"
        if not isinstance(g, str):
            for k, shell in shells.items():
                if k in u and isinstance(shell, int) and abs(g - shell) < max(64, shell * 0.02):
                    urteil = "shell"; break
        ergebnis.append({"url": u, "host": urllib.parse.urlsplit(u).netloc,
                         "bytes": g if not isinstance(g, str) else None,
                         "verdict": urteil, "woher": sorted(quellen[u])})
    for u in uebersprungen:
        ergebnis.append({"url": u, "host": urllib.parse.urlsplit(u).netloc, "bytes": None,
                         "verdict": "uebersprungen", "woher": sorted(quellen[u])})

    je_host = collections.defaultdict(collections.Counter)
    for e in ergebnis:
        je_host[e["host"]][e["verdict"].split(" ")[0]] += 1
    print("\nje Host:")
    for h in sorted(je_host, key=lambda x: -sum(je_host[x].values())):
        z = je_host[h]
        schlecht = sum(n for k, n in z.items() if k not in ("ok", "shell", "uebersprungen"))
        mark = "  <-- " if schlecht else "       "
        print(f"  {h:<38}{mark}" + ", ".join(f"{k} {n}" for k, n in sorted(z.items())))

    kaputt = [e for e in ergebnis if e["verdict"] not in ("ok", "shell", "uebersprungen")]
    print(f"\n{sum(1 for e in ergebnis if e['verdict']=='ok')} von {len(ergebnis)} antworten mit Inhalt, "
          f"{sum(1 for e in ergebnis if e['verdict']=='shell')} sind hier nicht nachweisbar, "
          f"{len(kaputt)} antworten nicht.")

    aus = pathlib.Path(a.json_out)
    aus.parent.mkdir(parents=True, exist_ok=True)
    aus.write_text(json.dumps({"geprueft_am": time.strftime("%Y-%m-%d %H:%M"),
                               "shells": {k: str(v) for k, v in shells.items()},
                               "results": ergebnis}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("geschrieben:", aus)


if __name__ == "__main__":
    main()
