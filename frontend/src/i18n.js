// German and English interface text for both finders.
//
// The audience is German researchers working with German data, so German is the default
// whenever the browser asks for it; the choice is persisted per browser like the theme.
// Product names (SOEP Variable Finder, GeoDB Geodata Index) and the source labels inside the
// data are NOT translated: the record labels come from the portals themselves, and renaming
// them here would break the link between what the finder shows and what the source calls it.

export const LANGUAGES = [
  { value: 'de', label: 'Deutsch' },
  { value: 'en', label: 'English' },
]

export const STRINGS = {
  en: {
    'theme.aria': 'Theme',
    'theme.default': 'Default',
    'theme.dark': 'Dark',
    'theme.light': 'Light',
    'lang.aria': 'Language',

    'blurb.inkar': 'Semantic search across German georeferenced data sources. Describe the concept you need data on; every hit links out to the source that holds it, and says how precisely that link lands.',
    'blurb.soep': 'Multilingual semantic search over SOEP-Core variable metadata.',
    'blurb.all': 'Semantic search over SOEP variables and regional indicators.',
    'action.clear': 'Clear',
    'action.ask': 'Ask',
    'action.searching': 'Searching...',

    'filter.source': 'Search source',
    'filter.allSources': 'All metadata sources',
    'filter.datasetGeo': 'Dataset / sheet',
    'filter.datasetSoep': 'SOEP dataset',
    'filter.allDatasets': 'All datasets',
    'filter.sampleGroup': 'Sample / questionnaire',
    'filter.anySampleGroup': 'Any sample / questionnaire',
    'filter.spatialLevel': 'Spatial level',
    'filter.anyLevel': 'Any level',
    'filter.theme': 'Theme',
    'filter.any': 'Any',
    'filter.startYear': 'Start year',
    'filter.endYear': 'End year',
    'filter.topK': 'Returned records',
    'filter.regionalOnly': 'Regionalized only',
    'filter.includeRaw': 'Include raw questionnaire files ({count})',
    'filter.includeRawTitle': 'soepdata/raw: the raw questionnaire files behind the analysis datasets',
    'filter.active': 'Active: {source}',
    'filter.years': 'indexed years {min}-{max}',
    'filter.indexBuilt': 'index as of {date}',

    'placeholder.inkar': 'Example: regional indicators for rural infrastructure, employment, childcare, or commuting (Shift+Enter for new line)',
    'placeholder.soep': 'Example: net individual income from labour; household equivalised income; years of education (Shift+Enter for new line)',
    'placeholder.all': 'Example: net labour income and regional childcare coverage by district (Shift+Enter for new line)',

    'results.empty': 'No results yet. Enter a query on the left.',
    'results.title': 'Results',
    'results.exportAll': 'Export all rows',
    'results.selected': '{count} selected',
    'results.searching': 'Searching semantic metadata index...',
    'results.pipeline': 'Retrieval: {embedding} | Generator: {llm} | Mode: {responseMode} | Index: {index}',
    'results.generatorOff': 'disabled',
    'results.retrievalOnly': 'retrieval-only',
    'results.portalsOnly': 'No indicator-level hit for this question. The portals below are the places to look.',

    'col.select': 'Select',
    'col.record': 'Record',
    'col.source': 'Source',
    'col.score': 'Score',
    'col.coverage': 'Coverage',
    'col.why': 'Why useful',
    'col.link': 'Get it from',
    'row.selectAria': 'Select {name}',
    'row.context': 'View extracted context',
    'row.noDescription': 'No description found.',
    'row.alsoIn': 'also in: {datasets}',
    'row.noYears': 'No explicit years',
    'row.noLevel': 'No spatial level',
    'row.noLink': 'No link',
    'row.codebook': 'codebook',

    'portals.heading': 'Data portals to search in',
    'portals.discontinued': 'no longer updated',

    'chat.you': 'You:',
    'chat.filters': 'Filters: {summary}',
    'chat.error': 'Error: {message}',

    'link.indicator': 'opens the indicator',
    'link.indicator.short': 'indicator link',
    'link.table': 'opens the exact table',
    'link.table.short': 'table link',
    'link.statistic': 'opens the statistic that contains it',
    'link.statistic.short': 'statistic link',
    'link.dataset': 'opens the dataset that contains it',
    'link.dataset.short': 'dataset link',
    'link.portal': 'opens the portal; search from there',
    'link.portal.short': 'portal link',
    'link.unverified': '{label} (documented form; the target portal is a JavaScript app, so the link could not be verified server-side)',

    'level.Gemeinden': 'Municipality (Gemeinde / LAU)',
    'level.Kreise': 'District (Kreis / NUTS3)',
    'level.NUTS2': 'NUTS2 region',
    'level.Bundesländer': 'Federal state (Bundesland / NUTS1)',
    'level.Regierungsbezirke': 'Government region (Regierungsbezirk)',
    'level.Bezirke': 'Borough (Bezirk)',
    'level.Ortsteile': 'Locality (Ortsteil / Bezirksregion)',
    'level.PLZ': 'Postcode (PLZ)',
    'level.Adressen/Koordinaten': 'Address / coordinates',
    'level.Bundestagswahlkreise': 'Federal constituency (Wahlkreis)',
    'level.Rasterzellen': 'Grid cells (raster)',
    'level.Bund': 'Germany (national)',
    'level.Weitere Gliederungen': 'Other spatial breakdowns',

    'cite.prefix': 'Please cite: Wandel, K. (2026). {title}. Zenodo.',
    'legal.imprint': 'Imprint',
    'legal.privacy': 'Privacy',
    'legal.sources': 'Data sources and attribution',
  },

  de: {
    'theme.aria': 'Darstellung',
    'theme.default': 'Systemvorgabe',
    'theme.dark': 'Dunkel',
    'theme.light': 'Hell',
    'lang.aria': 'Sprache',

    'blurb.inkar': 'Semantische Suche über deutsche georeferenzierte Datenquellen. Beschreiben Sie das Konzept, zu dem Sie Daten brauchen; jeder Treffer verlinkt auf die Quelle, die die Daten hält, und nennt, wie genau der Link dort landet.',
    'blurb.soep': 'Mehrsprachige semantische Suche über die Variablenmetadaten des SOEP-Core.',
    'blurb.all': 'Semantische Suche über SOEP-Variablen und regionale Indikatoren.',
    'action.clear': 'Verlauf löschen',
    'action.ask': 'Suchen',
    'action.searching': 'Suche läuft...',

    'filter.source': 'Datenquelle',
    'filter.allSources': 'Alle Metadatenquellen',
    'filter.datasetGeo': 'Datensatz / Tabellenblatt',
    'filter.datasetSoep': 'SOEP-Datensatz',
    'filter.allDatasets': 'Alle Datensätze',
    'filter.sampleGroup': 'Stichprobe / Fragebogen',
    'filter.anySampleGroup': 'Alle Stichproben / Fragebögen',
    'filter.spatialLevel': 'Räumliche Ebene',
    'filter.anyLevel': 'Alle Ebenen',
    'filter.theme': 'Thema',
    'filter.any': 'Alle',
    'filter.startYear': 'Startjahr',
    'filter.endYear': 'Endjahr',
    'filter.topK': 'Anzahl Treffer',
    'filter.regionalOnly': 'Nur regionalisierte Merkmale',
    'filter.includeRaw': 'Rohdaten der Fragebögen einbeziehen ({count})',
    'filter.includeRawTitle': 'soepdata/raw: die Rohdateien der Fragebögen hinter den Analysedatensätzen',
    'filter.active': 'Aktiv: {source}',
    'filter.years': 'indexierte Jahre {min}-{max}',
    'filter.indexBuilt': 'Index vom {date}',

    'placeholder.inkar': 'Beispiel: regionale Indikatoren zu ländlicher Infrastruktur, Beschäftigung, Kinderbetreuung oder Pendeln (Shift+Enter für eine neue Zeile)',
    'placeholder.soep': 'Beispiel: Nettoerwerbseinkommen; bedarfsgewichtetes Haushaltseinkommen; Bildungsjahre (Shift+Enter für eine neue Zeile)',
    'placeholder.all': 'Beispiel: Nettoerwerbseinkommen und Betreuungsquote nach Kreisen (Shift+Enter für eine neue Zeile)',

    'results.empty': 'Noch keine Treffer. Geben Sie links eine Anfrage ein.',
    'results.title': 'Treffer',
    'results.exportAll': 'Alle Zeilen exportieren',
    'results.selected': '{count} ausgewählt',
    'results.searching': 'Semantischer Metadatenindex wird durchsucht...',
    'results.pipeline': 'Retrieval: {embedding} | Generator: {llm} | Modus: {responseMode} | Index: {index}',
    'results.generatorOff': 'deaktiviert',
    'results.retrievalOnly': 'nur Retrieval',
    'results.portalsOnly': 'Kein Treffer auf Indikatorebene. Die Portale unten sind die Stellen, an denen zu suchen ist.',

    'col.select': 'Auswahl',
    'col.record': 'Merkmal',
    'col.source': 'Quelle',
    'col.score': 'Score',
    'col.coverage': 'Abdeckung',
    'col.why': 'Warum passend',
    'col.link': 'Bezug über',
    'row.selectAria': '{name} auswählen',
    'row.context': 'Beschreibung anzeigen',
    'row.noDescription': 'Keine Beschreibung vorhanden.',
    'row.alsoIn': 'auch in: {datasets}',
    'row.noYears': 'Keine Jahresangabe',
    'row.noLevel': 'Keine räumliche Ebene',
    'row.noLink': 'Kein Link',
    'row.codebook': 'Codebook',

    'portals.heading': 'Datenportale zum Weitersuchen',
    'portals.discontinued': 'wird nicht mehr aktualisiert',

    'chat.you': 'Anfrage:',
    'chat.filters': 'Filter: {summary}',
    'chat.error': 'Fehler: {message}',

    'link.indicator': 'öffnet den Indikator',
    'link.indicator.short': 'Indikator-Link',
    'link.table': 'öffnet genau diese Tabelle',
    'link.table.short': 'Tabellen-Link',
    'link.statistic': 'öffnet die Statistik, die das Merkmal enthält',
    'link.statistic.short': 'Statistik-Link',
    'link.dataset': 'öffnet den Datensatz, der das Merkmal enthält',
    'link.dataset.short': 'Datensatz-Link',
    'link.portal': 'öffnet das Portal; dort weitersuchen',
    'link.portal.short': 'Portal-Link',
    'link.unverified': '{label} (dokumentierte Form; das Zielportal ist eine JavaScript-Anwendung, der Link konnte serverseitig nicht geprüft werden)',

    'level.Gemeinden': 'Gemeinden (LAU)',
    'level.Kreise': 'Kreise und kreisfreie Städte (NUTS3)',
    'level.NUTS2': 'NUTS2-Regionen',
    'level.Bundesländer': 'Bundesländer (NUTS1)',
    'level.Regierungsbezirke': 'Regierungsbezirke',
    'level.Bezirke': 'Bezirke',
    'level.Ortsteile': 'Ortsteile und Bezirksregionen',
    'level.PLZ': 'Postleitzahlen',
    'level.Adressen/Koordinaten': 'Adressen und Koordinaten',
    'level.Bundestagswahlkreise': 'Bundestagswahlkreise',
    'level.Rasterzellen': 'Rasterzellen',
    'level.Bund': 'Bund (Deutschland insgesamt)',
    'level.Weitere Gliederungen': 'Weitere räumliche Gliederungen',

    'cite.prefix': 'Zitiervorschlag: Wandel, K. (2026). {title}. Zenodo.',
    'legal.imprint': 'Impressum',
    'legal.privacy': 'Datenschutz',
    'legal.sources': 'Datenquellen und Attribution',
  },
}

export function detectLanguage() {
  try {
    const stored = localStorage.getItem('geolab_lang')
    if (stored === 'de' || stored === 'en') return stored
  } catch (e) { /* private mode: fall through to the browser preference */ }
  try {
    const preferred = (navigator.languages || [navigator.language || 'en']).find(Boolean) || 'en'
    return String(preferred).toLowerCase().startsWith('de') ? 'de' : 'en'
  } catch (e) {
    return 'en'
  }
}

// t('filter.active', { source: 'INKAR' }) -> "Aktiv: INKAR". A missing key falls back to
// English and then to the key itself, so a half-translated build degrades visibly but works.
export function makeTranslator(language) {
  const table = STRINGS[language] || STRINGS.en
  return function t(key, vars) {
    let text = table[key]
    if (text === undefined) text = STRINGS.en[key]
    if (text === undefined) return key
    if (!vars) return text
    return Object.keys(vars).reduce(
      (out, name) => out.replaceAll(`{${name}}`, String(vars[name] ?? '')),
      text,
    )
  }
}

// Topic paths from SOEP are long ("Arbeit und Beschaeftigung > Erwerbsstatus > ..."), and a
// dropdown truncates them so two different paths look identical. The last two segments are
// what distinguishes them; the full path stays available as the option's title.
export function shortenPath(value, segments = 2) {
  const parts = String(value || '').split('>').map((part) => part.trim()).filter(Boolean)
  if (parts.length <= segments) return value
  return '… ' + parts.slice(-segments).join(' > ')
}
