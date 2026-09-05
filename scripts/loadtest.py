"""How many people can search at the same time before it hurts.

Measured against the deployed services, not a local copy, because the answer is a property of the
VM: four cores, CPU inference, one uvicorn worker per finder whose search endpoint is deliberately
synchronous so FastAPI runs it in a threadpool.

Results on 2026-09-05 (GeoDB and SOEP behave identically, they are the same code):

    concurrent   median   slowest   throughput
             1     1.2s      1.2s       0.8/s
             3     4.5s      4.7s      0.64/s
             5     5.5s      6.6s      0.76/s
            10    12.2s     13.1s      0.76/s
            15    20.2s     20.9s      0.72/s
            25    25.0s     26.1s      0.96/s

Nothing failed at any level: no timeouts, no 502s, no wrong results, and a single query is back to
1.0s the moment the burst is over. The machine simply serves about one search per second in total
and everyone else queues, so the wait is roughly (number of people) x 1.2s. Both finders share the
four cores: five on each is the same as ten on one.

    python scripts/loadtest.py
"""
import json, statistics, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

DIENSTE = {
    'GeoDB': ('https://geodb.geolab.soz.uni-bielefeld.de/api/soep/advice', [
        'Erreichbarkeit von Apotheken im ländlichen Raum', 'broadband availability by municipality',
        'Arbeitslosenquote auf Kreisebene', 'Bevölkerungsdichte Gemeinden', 'Pendlerverflechtungen',
        'Krankenhausbetten je Einwohner', 'Kinderbetreuungsquote', 'Mietpreise Wohnungsmarkt',
        'Verkehrsunfälle Radverkehr', 'Bodenrichtwerte']),
    'SOEP': ('https://soep-faiss.geolab.soz.uni-bielefeld.de/api/soep/advice', [
        'net individual income from labour', 'Geschlechterrollen', 'life satisfaction',
        'political interest', 'household composition', 'migration background',
        'working hours per week', 'health satisfaction', 'trust in institutions', 'Wohndauer']),
}

def frage(url, text, top_k=12, timeout=300):
    daten = json.dumps({'question': text, 'top_k': top_k}).encode()
    req = urllib.request.Request(url, data=daten, headers={'Content-Type': 'application/json'})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            ergebnis = json.loads(r.read())
        return time.perf_counter() - t0, len(ergebnis.get('recommended_variables') or []), None
    except Exception as e:
        return time.perf_counter() - t0, 0, f"{type(e).__name__}: {str(e)[:40]}"

def runde(name, url, fragen, gleichzeitig):
    aufgaben = [fragen[i % len(fragen)] for i in range(gleichzeitig)]
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=gleichzeitig) as pool:
        ergebnisse = list(pool.map(lambda q: frage(url, q), aufgaben))
    gesamt = time.perf_counter() - t0
    zeiten = [z for z, _, f in ergebnisse if f is None]
    fehler = [f for _, _, f in ergebnisse if f]
    treffer = [n for _, n, f in ergebnisse if f is None]
    if not zeiten:
        print(f"  {name:<6} {gleichzeitig:>2} gleichzeitig: alles gescheitert {fehler[:1]}"); return
    print(f"  {name:<6} {gleichzeitig:>2} gleichzeitig | "
          f"Median {statistics.median(zeiten):5.1f}s | langsamster {max(zeiten):5.1f}s | "
          f"Wanduhr {gesamt:5.1f}s | Durchsatz {gleichzeitig/gesamt:4.2f}/s | "
          f"Treffer {min(treffer)}-{max(treffer)} | Fehler {len(fehler)}")

if __name__ == '__main__':
    print("=== Aufwärmen (Modelle sind geladen, aber der erste Aufruf zählt nicht)")
    for name, (url, fragen) in DIENSTE.items():
        z, n, f = frage(url, fragen[0]); print(f"  {name}: {z:.1f}s, {n} Treffer, {f or 'ok'}")
    print("\n=== Last")
    for name, (url, fragen) in DIENSTE.items():
        for g in (1, 3, 5, 10):
            runde(name, url, fragen, g)
            time.sleep(2)
