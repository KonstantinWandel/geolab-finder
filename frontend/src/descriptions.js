// Presentation only: source descriptions and retrieval documents are never rewritten here.
const SOEP_FIELDS = {
  'Offizielle Erläuterung': ['note', 'de'], 'Official note': ['note', 'en'],
  'Fragetext': ['question', 'de'], 'Question wording': ['question', 'en'],
  'Antwortkategorien': ['categories', 'de'], 'Verteilung': ['distribution', ''],
}
const REGIONAL_FIELDS = ['Aussage', 'Indikatorberechnung', 'Herkunftsstatistiken',
  'Merkmalsbeschreibungen', 'Regionale Besonderheiten', 'Weiterführende Informationen']

export function descriptionSections(row, language = 'en') {
  const raw = String(row.description_original || row.rich_description || row.stats_summary || '')
  if (row.source_key === 'soep' && row.soep_version === 'v41') {
    const fields = new Map()
    for (const line of raw.split('\n')) {
      const colon = line.indexOf(':')
      const field = SOEP_FIELDS[line.slice(0, colon)]
      if (field) fields.set(`${field[0]}:${field[1]}`, line.slice(colon + 1).trim())
    }
    const sections = ['note', 'question', 'categories', 'distribution'].flatMap((kind) => {
      const preferred = fields.get(`${kind}:${language}`)
      const fallbackLanguage = language === 'en' ? 'de' : 'en'
      let text = preferred || fields.get(`${kind}:${fallbackLanguage}`) || fields.get(`${kind}:`)
      const sourceLanguage = preferred ? language : fields.has(`${kind}:${fallbackLanguage}`) ? fallbackLanguage : ''
      if (!text) return []
      if (kind === 'question') {
        // Only exact repeated wording is removed; different questionnaire variants stay intact.
        text = [...new Set(text.split(' | ').map((part) => part.trim()))].join('\n\n')
      }
      return [{ kind, text, language: sourceLanguage }]
    })
    if (sections.length) return sections
  }
  if (row.source_key === 'regionalatlas') {
    const pattern = new RegExp(`(${REGIONAL_FIELDS.join('|')}):`, 'g')
    const matches = [...raw.matchAll(pattern)]
    if (matches.length) {
      const prefix = raw.slice(0, matches[0].index).trim()
      const intro = prefix && prefix.replace(/:$/, '').trim() !== String(row.label || '').trim()
        ? [{ kind: 'description', text: prefix, language: 'de' }] : []
      return [...intro, ...matches.map((match, i) => ({
        kind: 'regional', title: match[1], language: 'de',
        text: raw.slice(match.index + match[0].length, matches[i + 1]?.index ?? raw.length).trim(),
      })).filter((section) => section.text)]
    }
  }
  return raw ? [{ kind: 'description', text: raw, language: '' }] : []
}
