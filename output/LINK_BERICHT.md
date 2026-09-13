# Erreichbarkeit aller auswärtigen Verweise

Geprüft am **2026-09-13** mit `scripts/check_all_links.py`, das jede verschiedene Adresse aus
allen vier Beständen und aus den veröffentlichten Seiten einmal holt. Die Stichprobenprüfung
`check_geodb_links.py` beantwortet die Frage, ob eine Quelle überhaupt antwortet; diese hier
beantwortet die Frage, welcher einzelne Verweis ins Leere zeigt.

Urteile: **ok** (2xx und größer als die bekannte Fehlseite des Hosts), **shell** (2xx, aber so
groß wie die Antwort auf einen absichtlich falschen Code, also ein im Browser aufgebautes Portal,
hier nicht nachweisbar), **http-<code>**, **unreachable**, **uebersprungen** (INKAR/BBSR, laut
Absprache nicht selbsttätig angefragt).

## statistik.arbeitsagentur.de: kein Linkrot, ein laufender Ausfall

Der Anlass der Prüfung. Alle 28 BA-Adressen im Index antworten nicht, und das sieht zunächst
nach Linkrot aus. Es ist keiner.

* Der Rechner ist da: Port 443 nimmt die Verbindung an, Port 80 antwortet mit einer ganz
  gewöhnlichen 301 auf https. Abgebrochen wird erst der TLS-Handschlag, vom Gegenüber.
* Es liegt nicht an unserem Werkzeug. Zurückgesetzt werden gleichermaßen: curl mit und ohne
  ALPN, erzwungenes HTTP/1.1, TLS 1.2, eine gelockerte Cipher-Liste, Python, und ein echtes
  Chromium. Der Browser ist hier der entscheidende Versuch, weil eine Sperre gegen
  Nicht-Browser-Verkehr genau so aussieht.
* Es liegt nicht an diesem Rechner. Die geolab-VM im Uni-Netz wird genauso zurückgesetzt.
* Es liegt nicht an unseren Netzen. Konstantin erreicht die Seite am selben Tag von seinem PC,
  von diesem Rechner, vom Telefon, innerhalb und außerhalb des VPN nicht.

**Wann es angefangen hat**, unabhängig belegt über das Internet Archive: die Startseite wurde
dort zuletzt am **2026-09-12 um 17:16** mit Status 200 geholt, davor über ein Jahr hinweg
monatlich ohne Lücke. Der Ausfall hat also nach dem Abend des 12.09. begonnen.

**Die Adressen selbst sind heil.** Jeder der geprüften Glossar-Tiefenverweise
(`Glossar-Nav.html?lv2=<id>`) lieferte beim letzten Archivbesuch zwischen Dezember 2025 und
September 2026 Status 200. Die Form der Adresse ist also haltbar, es gibt nichts zu reparieren.

**Was daraus folgt:** nichts ändern. Die Verweise sind richtig, die Quelle ist vorübergehend weg.
Erneut prüfen mit

```bash
cd ~/kwandel/destatis-rag
~/miniconda3/envs/research/bin/python scripts/check_all_links.py --host statistik.arbeitsagentur.de
```

Bewusst **nicht** in `data_sources/registry/known_url_issues.json` eingetragen: diese Datei ist
für Adressen, die von außen grundsätzlich nicht prüfbar sind. Ein echter Ausfall gehört gemeldet,
und der wöchentliche Prüflauf soll ihn melden, solange er dauert.


## Der Gesamtstand

5002 verschiedene Adressen auf 131 Hosts.

| | Zahl | was das heißt |
|---|---:|---|
| **ok** | 3128 | antwortet mit Inhalt, größer als die Fehlseite des Hosts |
| **nicht nachweisbar** | 1167 | antwortet, aber mit derselben Hülle wie auf einen falschen Code |
| **übersprungen** | 658 | INKAR/BBSR, laut Absprache nicht selbsttätig angefragt |
| **antwortet nicht** | 49 | siehe unten; 29 davon sind der BA-Ausfall |

| Host | Adressen | ok | Hülle | Fehler | übersprungen |
|---|---:|---:|---:|---:|---:|
| `www.regionalstatistik.de` | 1526 | 1526 | - | - | - |
| `geodb.geolab.soz.uni-bielefeld.de` | 655 | 1 | - | - | 654 |
| `ergebnisse.zensus2022.de` | 544 | 1 | 543 | - | - |
| `www-genesis.destatis.de` | 521 | 220 | 301 | - | - |
| `www.wegweiser-kommune.de` | 394 | 394 | - | - | - |
| `regionalatlas.statistikportal.de` | 233 | 1 | 232 | - | - |
| `www.gbe-bund.de` | 202 | 201 | - | 1 | - |
| `opendata.dwd.de` | 137 | 137 | - | - | - |
| `monitor.ioer.de` | 91 | 0 | 91 | - | - |
| `www.forschungsdatenzentrum.de` | 76 | 76 | - | - | - |
| `www.opendata-oepnv.de` | 73 | 73 | - | - | - |
| `daten.gdz.bkg.bund.de` | 70 | 70 | - | - | - |
| `www.deutschlandatlas.bund.de` | 63 | 63 | - | - | - |
| `gdk.gdi-de.org` | 59 | 59 | - | - | - |
| `fdz.iab.de` | 35 | 35 | - | - | - |
| `gtfs.org` | 32 | 32 | - | - | - |
| `fdz.rwi-essen.de` | 29 | 29 | - | - | - |
| `statistik.arbeitsagentur.de` | 29 | 0 | - | 29 | - |
| `wiki.openstreetmap.org` | 27 | 27 | - | - | - |
| `service.destatis.de` | 19 | 19 | - | - | - |
| *111 weitere Hosts mit unter 19 Adressen* | 187 | 164 | - | 19 | 4 |

**Die Hülle ist kein Mangel unserer Verweise.** Zensus, die Bundes-GENESIS, der Regionalatlas und
der IÖR-Monitor bauen ihre Seiten erst im Browser auf, also kommt auf jede Adresse dieselbe
Antwort, ob der Code stimmt oder nicht. Gemessen statt vermutet: 543 Zensus-Adressen ergaben genau
EINE Antwortgröße, 233 Regionalatlas-Adressen genau eine, und bei der Bundes-GENESIS gilt das für
alle 301 geprüften Verweise der Form `operation=table`. Zum Vergleich die Regionalstatistik: 1.526
Adressen, sämtlich mit echtem Inhalt und 511 verschiedenen Größen auf den ersten 542.

Für diese Hosts prüft der Lauf deshalb nur eine Stichprobe und spart 3.687 Anfragen an
Bundesserver, die nichts erbracht hätten. Dass dabei nichts verlorengeht, ist nachgerechnet: die
2.725 nicht angefassten GENESIS-Adressen sind ausnahmslos `operation=table`, also dieselbe
Familie, und alle 220 Verweise der Form `statistic/<code>`, die dort echten Inhalt liefern, wurden
geprüft. Wer eine Hüllen-Adresse wirklich nachweisen will, braucht einen Browser, so wie
`check_ioer_links.py` es für den IÖR-Monitor tut.

## Was nicht antwortet, einzeln durchgesehen

Jeder Fall unten wurde zusätzlich in einem echten Chromium geöffnet. Das ist keine Förmlichkeit:
von den 20 Fehlern außerhalb des BA-Ausfalls sind **zwei** echt kaputt, einer war ein Fehler
meines eigenen Prüfers, der Rest ist Bot-Abwehr.

### Echt kaputt

* **`gis.uba.de/maps/?lang=de#/apps/laermkartierung`**, im GeoDB-Index, im Planer-Katalog und auf
  der Seite. Die Kartenanwendung des UBA zur Lärmkartierung antwortet mit 404, im Browser genauso.
  Sie wurde am **06.09.2026 von Hand geöffnet und lief**, ist also in der Woche danach
  verschwunden. Selbst das UBA verlinkt auf seiner eigenen Seite "Lärmkarten" noch eine Adresse
  dieser Anwendung, und auch die ist 404, es ist also die ganze Anwendung und nicht unsere Kopie
  der Adresse. **Berichtigt** in `build_geodb_metadata.py`: der Satz zeigt jetzt auf
  `umweltbundesamt.de/themen/laerm/umgebungslaermrichtlinie/laermkarten`, die lebt, vom UBA
  gepflegt wird und weiterführt, sobald die Anwendung zurück ist. Die anderen fünf Adressen
  derselben Gruppe wurden nachgeprüft und antworten alle. Wirksam wird das mit dem nächsten
  Neubau des Index.
* **`http://platform.here.com`**, nur auf der Seite. Über http verweigert der Rechner die
  Verbindung, über https antwortet er normal. Der Verweis gehört auf `https://`.
* Am Rande, ebenfalls nur auf der Seite: **`https://usgs.gov/`** löst im DNS nicht auf,
  `www.usgs.gov` schon.

### Kein Mangel, sondern Bot-Abwehr

* **doi.org, 7 Verweise.** Im Browser kommt Cloudflares "Just a moment...". Einer löst sauber auf;
  die beiden Zenodo-DOI sind über die DataCite-Schnittstelle geprüft und stehen dort als
  `findable` mit den richtigen Titeln. Es sind unsere eigenen Veröffentlichungen.
* **ekvv.uni-bielefeld.de, 3 Personenseiten.** Antwortet mit einer eigenen Zugriffsseite des
  Bielefelder Informationssystems, nicht mit einem Fehler.
* **linkedin.com, 3 Profile.** HTTP 999, die Standardabwehr von LinkedIn.
* **hochschulkompass.de.** HTTP 400, die Seite baut sich im Browser trotzdem vollständig auf.
  Steht seit dem 03.09.2026 mit Begründung in `known_url_issues.json`.
* **maps.nls.uk/projects/subscription-api.** HTTP 405 auf GET: das ist eine Schnittstelle und
  keine Seite, 405 ist dort die richtige Antwort.

### Ein Fehler meines Prüfers, kein kaputter Verweis

Ein `gbe-bund`-Verweis meldete 500. Die Adresse stammt aus fertigem HTML, wo ein `&` als `&amp;`
geschrieben steht, und ohne Rückübersetzung habe ich eine Adresse angefragt, die es nie gab.
Behoben, die fünf betroffenen Adressen sind erneut geprüft und antworten. Ein zweiter
`gbe-bund`-Verweis mit 502 antwortet im Browser sofort mit 200, das war vorübergehend.

## Was dieser Lauf beim BBSR angerichtet hat

Beim ersten Durchgang lief die Prüfung auch über unsere 654 INKAR-Verweise der Form
`geodb.geolab…/api/inkar/open/<M_ID>`. Dieser Punkt legt beim ersten Öffnen eine gespeicherte
Abfrage auf dem BBSR-Server an, und genau deshalb ist er faul gebaut. Der Lauf hat 353 davon
angelegt, also genau die Reihe selbsttätiger Anfragen, die die Absprache ausschließt. Alle 353
sind noch am selben Tag gelöscht worden, die vier aus echter Nutzung vom 6. und 10.09. blieben
stehen und antworten weiter; die Ablage war vorher gesichert. Die Sperrliste im Prüfskript kannte
nur Hostnamen und war damit wirkungslos, weil die schreibende Adresse unsere eigene ist. Sie
sperrt jetzt den Pfad `/api/inkar/open/` mit.
