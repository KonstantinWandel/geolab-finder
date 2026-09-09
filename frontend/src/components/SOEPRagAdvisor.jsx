import { useEffect, useMemo, useRef, useState } from 'react'
import { makeTranslator, shortenPath, datasetLabel, sortSpatialLevels } from '../i18n'

// The project site carries the imprint, the privacy statement and the attribution list.
const GEOLAB_SITE = 'https://geolab.soz.uni-bielefeld.de'

// One facet: a dropdown that opens onto checkboxes. A plain <select> holds exactly one value, so
// comparing two sources or three spatial levels meant running the same search once per value.
// Collapsed it shows what is chosen; nothing checked means no restriction, which is the honest
// reading of an empty list. The list expands in flow rather than as an overlay, because the filter
// column scrolls and an absolutely positioned panel would be clipped by it.
function FacetChecks({ label, options, selected, onToggle, onClear, allLabel, emptyHint, closeLabel }) {
  const [open, setOpen] = useState(false)
  // Which way the menu opens and how tall it may be, measured rather than assumed: a fixed
  // height ran off the bottom of the window for three of the four facets on a 900px screen.
  const [place, setPlace] = useState({ up: false, maxHeight: 420 })
  const box = useRef(null)

  const measure = () => {
    if (!box.current) return
    const rect = box.current.getBoundingClientRect()
    const below = window.innerHeight - rect.bottom - 12
    const above = rect.top - 12
    const up = above > below
    setPlace({ up, maxHeight: Math.max(180, Math.min(560, up ? above : below)) })
  }

  // An overlay has to close when the reader looks away from it: a click anywhere else, or Escape.
  // Clicking another facet's trigger therefore closes this one, so only one menu is ever open.
  // While it is open, scrolling or resizing changes the room it has, so it is measured again.
  useEffect(() => {
    if (!open) return undefined
    window.addEventListener('resize', measure)
    window.addEventListener('scroll', measure, true)
    const onPointer = (event) => {
      if (box.current && !box.current.contains(event.target)) setOpen(false)
    }
    const onKey = (event) => { if (event.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onPointer)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onPointer)
      document.removeEventListener('keydown', onKey)
      window.removeEventListener('resize', measure)
      window.removeEventListener('scroll', measure, true)
    }
  }, [open])

  const chosen = selected.length
  const summary = chosen === 0
    ? allLabel
    : (chosen === 1
      ? (options.find((option) => option.value === selected[0])?.label || selected[0])
      : `${chosen}/${options.length}`)
  return (
    <div className={`facet${open ? ' is-open' : ''}${open && place.up ? ' drops-up' : ''}`} ref={box}>
      <label className="facet-label">{label}</label>
      <button
        type="button"
        className="facet-trigger"
        aria-expanded={open}
        onClick={() => {
          if (!open) measure()
          setOpen((value) => !value)
        }}
      >
        <span className={chosen ? 'facet-summary is-set' : 'facet-summary'}>{summary}</span>
        <span className="facet-caret" aria-hidden="true">{open ? '\u25B4' : '\u25BE'}</span>
      </button>
      {open && (
        <div className="facet-list" style={{ maxHeight: `${place.maxHeight}px` }}>
          {options.length === 0 && <p className="facet-empty">{emptyHint}</p>}
          {options.map((option) => (
            <label className="facet-item" key={option.value} title={option.title || option.label}>
              <input
                type="checkbox"
                checked={selected.includes(option.value)}
                onChange={() => onToggle(option.value)}
              />
              <span>{option.label}</span>
            </label>
          ))}
          <div className="facet-actions">
            {chosen > 0 && (
              <button type="button" className="facet-clear" onClick={onClear}>{allLabel}</button>
            )}
            <button type="button" className="facet-done" onClick={() => setOpen(false)}>{closeLabel}</button>
          </div>
        </div>
      )}
    </div>
  )
}

function SOEPRagAdvisor({ apiUrl, mode = 'all', language = 'en' }) {
  const t = makeTranslator(language)
  const isInkar = mode === 'inkar'
  const isSoep = mode === 'soep'
  const isAll = mode === 'all'
  const showRegionalFilters = isInkar || isAll
  const showSoepFilters = isSoep || isAll
  const STORAGE_KEY = `geolab_history_${mode}`
  const headerBlurb = t(isInkar ? 'blurb.inkar' : isSoep ? 'blurb.soep' : 'blurb.all')

  // Spatial levels are one concept with a translated label; an unmapped level falls back to
  // the German name the data uses, which is better than hiding it.
  const spatialLevelLabel = (level) => {
    const translated = t(`level.${level}`)
    return translated === `level.${level}` ? level : translated
  }

  // Per-finder citation (each deployment is archived on Zenodo under its own DOI).
  const CITATION = {
    soep: { title: 'SOEP Variable Finder', doi: '10.5281/zenodo.21134306' },
    inkar: { title: 'GeoDB Geodata Index', doi: '10.5281/zenodo.21134145' },
    all: { title: 'GeoLAB Metadata Finders', doi: '10.5281/zenodo.21134145' },
  }
  const cite = CITATION[mode] || CITATION.all

  const [question, setQuestion] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [filterOptions, setFilterOptions] = useState(null)
  // Values a source change made unavailable, kept only to say so once.
  const [droppedFilters, setDroppedFilters] = useState([])
  // Every facet holds a LIST of chosen values; an empty list means no restriction. The SOEP
  // deployment is the exception that pre-selects its own source, because it serves only that one.
  const [filters, setFilters] = useState({
    dataset_scope: isSoep ? ['soep'] : [],
    dataset_label: [],
    nuts_level: [],
    spatial_level: [],
    theme: [],
    year_start: '',
    year_end: '',
    regional_only: false,
    include_raw: false,
    sample_group: [],
    top_k: 12,
  })

  // How precisely a result's link lands on the thing it describes. Shown as a chip so a
  // user can tell "this opens the exact indicator" from "this opens a portal to search in".
  const LINK_LEVELS = ['indicator', 'table', 'statistic', 'dataset', 'portal']
  const linkLevel = (level) =>
    LINK_LEVELS.includes(level) ? { label: t(`link.${level}`), short: t(`link.${level}.short`) } : null

  // The API labels the facets it generates itself (source keys, sample groups, SOEP dataset
  // titles) in English, because those strings are also the export columns. They are translated
  // here by key, with the API's own label as the fallback, so a new key shows up in English
  // rather than disappearing.
  const apiLabel = (prefix, value, fallback) => {
    const translated = t(`${prefix}.${value}`)
    return translated === `${prefix}.${value}` ? (fallback || value) : translated
  }
  const sourceOptionLabel = (source) => apiLabel('source', source.value, source.label)
  const sampleOptionLabel = (group) => apiLabel('sample', group.value, group.label)
  const datasetOptionLabel = (label) => datasetLabel(label, language)

  // Human label for a SOEP sample/questionnaire group key (from the fetched facet).
  const sampleGroupLabel = (key) => {
    const group = (filterOptions?.sample_groups || []).find((g) => g.value === key)
    return group ? sampleOptionLabel(group) : null
  }

  const [chatHistory, setChatHistory] = useState([])
  const [selectedRows, setSelectedRows] = useState({})
  const [expandedRows, setExpandedRows] = useState({})
  const messagesEndRef = useRef(null)
  const latestMsgRef = useRef(null)

  useEffect(() => {
    const hist = localStorage.getItem(STORAGE_KEY)
    if (hist) {
      try {
        setChatHistory(JSON.parse(hist))
      } catch (e) {
        console.error(e)
      }
    }
  }, [])

  // Facets are re-fetched whenever the source changes, scoped to that source, so the
  // dataset/theme/level lists only ever offer values that exist within it. Any dependent
  // value that no longer exists is reset, otherwise a stale selection silently filters
  // every result away.
  useEffect(() => {
    let cancelled = false
    async function loadFilterOptions() {
      try {
        // include_raw is sent too: with raw files hidden, the SOEP dataset dropdown listed
        // 622 raw per-wave files that no result could ever come from.
        const query = new URLSearchParams()
        // The facet endpoint scopes to one source. With several chosen (or none) the unscoped
        // lists are the right answer, since every chosen source may contribute values.
        if ((filters.dataset_scope || []).length === 1) query.set('source', filters.dataset_scope[0])
        if (filters.include_raw) query.set('include_raw', 'true')
        const suffix = query.toString() ? `?${query}` : ''
        const res = await fetch(`${apiUrl}/soep/filter-options${suffix}`)
        if (!res.ok) return
        const data = await res.json()
        if (cancelled) return
        setFilterOptions(data)
        // A value that no longer exists in the new source's facets is dropped from the
        // selection. Keeping it would filter every result away with nothing on screen saying why.
        const dropped = []
        setFilters((current) => {
          const keep = (chosen, available) => {
            const gone = (chosen || []).filter((value) => !(available || []).includes(value))
            dropped.push(...gone)
            return (chosen || []).filter((value) => (available || []).includes(value))
          }
          return {
            ...current,
            dataset_label: keep(current.dataset_label, data.datasets),
            theme: keep(current.theme, data.themes),
            spatial_level: keep(current.spatial_level, data.spatial_levels),
            nuts_level: keep(current.nuts_level, data.nuts_levels),
            sample_group: keep(current.sample_group,
                                (data.sample_groups || []).map((g) => g.value)),
          }
        })
        setDroppedFilters(dropped)
      } catch (e) {
        console.error(e)
      }
    }
    loadFilterOptions()
    return () => {
      cancelled = true
    }
  }, [apiUrl, filters.dataset_scope, filters.include_raw])

  useEffect(() => {
    // Keep the TOP of the newest answer (the most relevant results) in view,
    // instead of jumping to the bottom of the results list.
    latestMsgRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [chatHistory])

  const sourceLabel = useMemo(() => {
    const chosen = filters.dataset_scope || []
    if (chosen.length !== 1) {
      return chosen.length === 0 ? t('filter.allSources') : t('filter.nSources', { count: chosen.length })
    }
    const source = filterOptions?.sources?.find((item) => item.value === chosen[0])
    return source ? sourceOptionLabel(source) : t('filter.allSources')
  }, [filterOptions, filters.dataset_scope, language])

  const updateFilter = (key, value) => {
    setFilters((current) => ({ ...current, [key]: value }))
  }

  const toggleFilter = (key, value) => {
    setFilters((current) => {
      const chosen = current[key] || []
      return {
        ...current,
        [key]: chosen.includes(value) ? chosen.filter((v) => v !== value) : [...chosen, value],
      }
    })
  }

  const clearFilter = (key) => setFilters((current) => ({ ...current, [key]: [] }))

  const handleAsk = async (e) => {
    if (e) e.preventDefault()
    if (!question.trim()) return

    const userQ = question.trim()
    const filterSnapshot = { ...filters }
    const newHist = [...chatHistory, { role: 'user', content: userQ, filters: filterSnapshot }]
    setChatHistory(newHist)
    setQuestion('')
    setLoading(true)
    setError(null)

    try {
      const res = await fetch(`${apiUrl}/soep/advice`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question: userQ,
          top_k: Number(filterSnapshot.top_k) || 12,
          // Send the SELECTED source, never the deployment mode. Sending `mode` here hard
          // filtered every GeoDB query to source_key "inkar" no matter what the dropdown said,
          // which made 18 of 19 sources unreachable through the UI while the API was fine.
          // Lists, or null when nothing is checked. The backend reads a list as "any of these".
          dataset_scope: filterSnapshot.dataset_scope?.length ? filterSnapshot.dataset_scope : null,
          dataset_label: filterSnapshot.dataset_label?.length ? filterSnapshot.dataset_label : null,
          nuts_level: filterSnapshot.nuts_level?.length ? filterSnapshot.nuts_level : null,
          spatial_level: filterSnapshot.spatial_level?.length ? filterSnapshot.spatial_level : null,
          theme: filterSnapshot.theme?.length ? filterSnapshot.theme : null,
          year_start: filterSnapshot.year_start ? Number(filterSnapshot.year_start) : null,
          year_end: filterSnapshot.year_end ? Number(filterSnapshot.year_end) : null,
          regional_only: Boolean(filterSnapshot.regional_only),
          include_raw: Boolean(filterSnapshot.include_raw),
          sample_groups: filterSnapshot.sample_group?.length ? filterSnapshot.sample_group : null,
        }),
      })

      if (!res.ok) {
        throw new Error(`Request failed (${res.status})`)
      }
      const data = await res.json()

      const updatedHist = [...newHist, { role: 'assistant', data }]
      setChatHistory(updatedHist)
      localStorage.setItem(STORAGE_KEY, JSON.stringify(updatedHist))
    } catch (err) {
      setError(err.message || 'Unknown error')
      const updatedHist = [...newHist, { role: 'error', content: err.message || 'Error occurred' }]
      setChatHistory(updatedHist)
    } finally {
      setLoading(false)
    }
  }

  // A question handed over in the URL (`?q=...`) is asked once, on load. That is what lets a
  // search box on the GeoLAB site lead straight into the finder with the search already run,
  // instead of dropping the visitor on an empty input. The parameter is removed from the
  // address bar afterwards so a reload does not silently ask it again.
  const handoverRef = useRef(null)
  useEffect(() => {
    try {
      const params = new URLSearchParams(window.location.search)
      const handover = (params.get('q') || '').trim().slice(0, 300)
      if (!handover) return
      handoverRef.current = handover
      setQuestion(handover)
      const url = new URL(window.location.href)
      url.searchParams.delete('q')
      window.history.replaceState({}, '', url.toString())
    } catch (e) {
      console.error(e)
    }
  }, [])

  useEffect(() => {
    if (handoverRef.current && question === handoverRef.current && !loading) {
      handoverRef.current = null
      handleAsk()
    }
  }, [question])

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleAsk()
    }
  }

  const formatScore = (score) => {
    if (score?.toFixed) return score.toFixed(3)
    return score || ''
  }

  const csvEscape = (value) => {
    const text = value == null
      ? ''
      : Array.isArray(value)
      ? value.join('; ')
      : typeof value === 'object'
      ? JSON.stringify(value)
      : String(value)
    return `"${text.replaceAll('"', '""')}"`
  }

  const rowForExport = (row) => ({
    source: row.source_label || '',
    dataset: row.dataset_label || row.dataset || '',
    record: row.variable_name || '',
    label: row.label || '',
    score: row.score ?? '',
    retrieval_score: row.retrieval_score ?? '',
    rerank_score: row.rerank_score ?? '',
    type: row.item_type || '',
    theme: row.theme || '',
    spatial_levels: (row.spatial_levels || []).join('; '),
    nuts_levels: (row.nuts_levels || []).join('; '),
    years: row.available_years_text || '',
    url: row.source_url || row.selector_url || row.indicator_url || '',
    portal_url: row.portal_url || '',
    link_level: row.link_level || '',
    link_verified: row.link_verified === false ? 'no' : 'yes',
    description: row.rich_description || row.search_description || row.stats_summary || '',
  })

  const downloadBlob = (content, filename, type) => {
    const blob = new Blob([content], { type })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
  }

  const exportRows = (rows, format, messageKey) => {
    const chosen = rows.filter((row, idx) => selectedRows[`${messageKey}:${row.item_id || row.variable_name || idx}`])
    const exportable = (chosen.length ? chosen : rows).map(rowForExport)
    if (!exportable.length) return
    const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')
    if (format === 'json') {
      downloadBlob(JSON.stringify(exportable, null, 2), `${mode}-metadata-results-${stamp}.json`, 'application/json')
      return
    }
    const columns = Object.keys(exportable[0])
    const csv = [
      columns.map(csvEscape).join(','),
      ...exportable.map((row) => columns.map((column) => csvEscape(row[column])).join(',')),
    ].join('\n')
    downloadBlob(csv, `${mode}-metadata-results-${stamp}.csv`, 'text/csv;charset=utf-8')
  }

  const toggleRow = (messageKey, row, idx) => {
    const key = `${messageKey}:${row.item_id || row.variable_name || idx}`
    setSelectedRows((current) => ({ ...current, [key]: !current[key] }))
  }

  // What a query was actually narrowed by. Every facet holds a list now, so joining the raw
  // values produced lines like "soep,All datasets,Any,Any"; this names only what restricts and
  // says so plainly when nothing does.
  const describeFilters = (f) => {
    const parts = []
    const named = (key, label, render = (v) => v) => {
      const chosen = f[key] || []
      if (!chosen.length) return
      parts.push(`${label}: ${chosen.map(render).join(', ')}`)
    }
    named('dataset_scope', t('filter.source'), (v) => {
      const source = filterOptions?.sources?.find((item) => item.value === v)
      return source ? sourceOptionLabel(source) : v
    })
    named('dataset_label', isInkar ? t('filter.datasetGeo') : t('filter.datasetSoep'), datasetOptionLabel)
    named('sample_group', t('filter.sampleGroup'), (v) => sampleGroupLabel(v) || v)
    named('spatial_level', t('filter.spatialLevel'), spatialLevelLabel)
    named('theme', t('filter.theme'), shortenPath)
    if (f.year_start || f.year_end) {
      parts.push(`${t('filter.startYear')}\u2013${t('filter.endYear')}: `
        + `${f.year_start || '…'}\u2013${f.year_end || '…'}`)
    }
    if (f.regional_only) parts.push(t('filter.regionalOnly'))
    if (f.include_raw) parts.push(t('filter.includeRawShort'))
    return parts.length ? parts.join(' · ') : t('filter.none')
  }

  const renderMessage = (msg, i) => {
    if (msg.role === 'user') {
      return (
        <div key={i} className="glass-panel" style={{ padding: '1rem', marginBottom: '1rem', background: 'var(--surface-2)' }}>
          <strong>{t('chat.you')}</strong>
          <p style={{ whiteSpace: 'pre-wrap', margin: '0.5rem 0 0 0' }}>{msg.content}</p>
          {msg.filters && (
            <p className="text-muted" style={{ fontSize: '0.8rem', margin: '0.5rem 0 0 0' }}>
              {t('chat.filters', { summary: describeFilters(msg.filters) })}
            </p>
          )}
        </div>
      )
    }
    if (msg.role === 'error') {
      return (
        <div key={i} className="error-message" style={{ marginBottom: '1rem' }}>
          {t('chat.error', { message: msg.content })}
        </div>
      )
    }
    if (msg.role === 'assistant') {
      const result = msg.data
      // Portal cards answer a different question from indicator hits ("go and search here" vs
      // "this variable exists"), so they get their own block instead of competing for rank.
      const allRows = result.recommended_variables || []
      const rows = allRows.filter((row) => row.source_key !== 'geoportal')
      const portalRows = allRows.filter((row) => row.source_key === 'geoportal')
      // How far the top hit stands out from the middle of the list, in cross-encoder space.
      // The absolute reranker score cannot tell an answerable question from an unanswerable
      // one (a conversational query with a correct rank-1 hit scores below every impossible
      // one), the margin can. Measured over 31 answerable and 27 impossible queries at this
      // top_k: below 0.015 it catches 18 of the 27 impossible ones and speaks up on 5 of the
      // 31 answerable ones, where the field really is flat. It is a note, never a filter:
      // nothing is hidden or reordered.
      const rerankScores = allRows
        .map((row) => Number(row.rerank_score))
        .filter((value) => Number.isFinite(value))
        .sort((a, b) => b - a)
      const median = rerankScores.length
        ? rerankScores[Math.floor(rerankScores.length / 2)]
        : 0
      const flatField = rerankScores.length > 2 && rerankScores[0] - median < 0.015

      const selectedCount = rows.filter((row, idx) => selectedRows[`${i}:${row.item_id || row.variable_name || idx}`]).length
      return (
        <div key={i} className="execution-result glass-panel" style={{ marginBottom: '1.5rem', padding: '1rem' }}>
          <div className="results-toolbar">
            <h3 style={{ margin: 0 }}>{t('results.title')}</h3>
            <div className="export-actions">
              <span className="text-muted">{selectedCount ? t('results.selected', { count: selectedCount }) : t('results.exportAll')}</span>
              <button type="button" className="btn-secondary" onClick={() => exportRows(rows, 'csv', i)}>CSV</button>
              <button type="button" className="btn-secondary" onClick={() => exportRows(rows, 'json', i)}>JSON</button>
            </div>
          </div>
          <p style={{ fontSize: '0.85rem', color: 'var(--muted)', marginTop: '0.6rem' }}>
            {/* The models stay named, that is honest transparency for a research tool. What
                went is the pipe-delimited debug line around them ("Generator: disabled | Mode:
                retrieval-only | Index: faiss"), which was internal wiring on a public page. */}
            {t('results.pipeline', { embedding: result.embedding_model })}
          </p>

          {flatField && rows.length > 0 && (
            <p className="results-flat">{t('results.flat')}</p>
          )}
          {rows.length === 0 && portalRows.length > 0 && (
            <p className="text-muted" style={{ marginTop: '0.4rem' }}>
              {t('results.portalsOnly')}
            </p>
          )}
          {/* One result per block, read top to bottom. The seven-column table this replaces
              needed 1040px of width, so it carried its own horizontal scrollbar inside its own
              vertical scrollbar inside the page, and about two results were visible at a time. */}
          <ol className="result-list">
            {rows.map((row, idx) => {
              const rowKey = `${i}:${row.item_id || row.variable_name || idx}`
              const href = row.source_url || row.selector_url || row.indicator_url
              const level = row.link_level ? linkLevel(row.link_level) : null
              // finest first here too, so the reader sees at once how far down the data goes
              const levels = sortSpatialLevels(row.nuts_levels).join(', ')
                || sortSpatialLevels(row.spatial_levels).join(', ')
              const description = row.rich_description || row.stats_summary || ''
              const expanded = Boolean(expandedRows[rowKey])
              return (
                <li className="result-item" key={`${row.item_id || row.variable_name}-${idx}`}>
                  <div className="result-head">
                    <input
                      type="checkbox"
                      className="result-select"
                      checked={Boolean(selectedRows[rowKey])}
                      onChange={() => toggleRow(i, row, idx)}
                      aria-label={t('row.selectAria', { name: row.variable_name || row.label || '' })}
                    />
                    <div className="result-headline">
                      <h4 className="result-label">{row.label || row.variable_name}</h4>
                      <div className="result-ident">
                        <code className="result-code">{row.variable_name}</code>
                        <span className="result-source">{row.source_label}</span>
                        {(row.dataset_label || row.dataset) && (
                          <span className="result-dataset">{datasetOptionLabel(row.dataset_label || row.dataset)}</span>
                        )}
                      </div>
                    </div>
                    <div className="result-rank" title={t('col.score')}>
                      <span className="result-rank-n">{idx + 1}</span>
                      <span className="result-score">{formatScore(row.score)}</span>
                    </div>
                  </div>

                  <dl className="result-facts">
                    <div>
                      <dt>{t('col.coverage')}</dt>
                      <dd>{row.available_years_text || t('row.noYears')}</dd>
                    </div>
                    {/* SOEP variables have no spatial level at all, so the field is left out
                        rather than filled with "no spatial level" on every single row. */}
                    {levels && (
                      <div>
                        <dt>{t('filter.spatialLevel')}</dt>
                        <dd>{levels}</dd>
                      </div>
                    )}
                    {row.theme && (
                      <div>
                        <dt>{t('filter.theme')}</dt>
                        <dd title={row.theme}>{shortenPath(row.theme)}</dd>
                      </div>
                    )}
                    {row.source_key === 'soep' && sampleGroupLabel(row.sample_group) && (
                      <div>
                        <dt>{t('filter.sampleGroup')}</dt>
                        <dd>{sampleGroupLabel(row.sample_group)}</dd>
                      </div>
                    )}
                  </dl>

                  {description && (
                    <p className={expanded ? 'result-desc is-open' : 'result-desc'}>{description}</p>
                  )}
                  {/* The API hint is a long technical note (Overpass query, INKAR code); it
                      belongs with the full description, not in the default view. */}
                  {expanded && row.api_hint && <p className="result-hint text-muted">{row.api_hint}</p>}
                  {row.also_in_datasets?.length > 0 && (
                    <p className="result-hint text-muted">
                      {t('row.alsoIn', { datasets: row.also_in_datasets.join(', ') })}
                    </p>
                  )}

                  {/* A link that only opens a search mask needs to say so. A colleague looked up
                      "Krankenhäuser", landed on a portal page where nothing of that name was
                      linked, and had no way of knowing she was expected to search again. The
                      name to search for is the record's own label, because that is what the
                      portal calls it, not the words she typed. */}
                  {(row.link_level === 'portal' || row.link_level === 'statistic') && (
                    <p className="result-hint-search">
                      {row.link_level === 'portal'
                        ? t('row.hintPortal', { name: `„${row.label || row.variable_name}“` })
                        : t('row.hintStatistic')}
                      {row.link_level === 'portal' && (
                        <button type="button" className="result-copy"
                                onClick={(event) => {
                                  const button = event.currentTarget
                                  navigator.clipboard?.writeText(row.label || row.variable_name || '')
                                  button.dataset.copied = '1'
                                  setTimeout(() => { delete button.dataset.copied }, 1600)
                                }}>
                          {t('row.copyTerm')}
                        </button>
                      )}
                    </p>
                  )}

                  {/* No trailing arrow on the link below. It pointed at whatever stood to its
                      right, first the portal fallback and then the precision chip, and a reader
                      followed it there. The link text already says that it opens something. */}
                  <div className="result-actions">
                    {href ? (
                      <a className="result-link" href={href} target="_blank" rel="noreferrer">
                        {row.source_key === 'inkar' ? 'INKAR' : t('row.open')}
                      </a>
                    ) : (
                      <span className="text-muted">{t('row.noLink')}</span>
                    )}
                    {level && (
                      <span
                        className="mini-chip link-chip"
                        title={row.link_verified === false
                          ? t('link.unverified', { label: level.label })
                          : level.label}
                      >
                        {level.label}{row.link_verified === false ? '*' : ''}
                      </span>
                    )}
                    {(row.api_hint || description.length > 240) && (
                      <button type="button" className="result-toggle"
                              onClick={() => setExpandedRows((c) => ({ ...c, [rowKey]: !c[rowKey] }))}>
                        {expanded ? t('row.less') : t('row.more')}
                      </button>
                    )}
                  </div>

                  {/* The fallback sits on its own line, and says what it is for. Beside the main
                      link it read as the thing the arrow pointed at, so people clicked it and
                      landed on an entry page instead of the record. */}
                  {row.portal_url && row.portal_url !== href && (
                    <p className="result-fallback">
                      {t('row.fallbackPrefix')}{' '}
                      <a href={row.portal_url} target="_blank" rel="noreferrer">{t('row.portal')}</a>
                    </p>
                  )}
                </li>
              )
            })}
          </ol>

          {portalRows.length > 0 && (
            <div className="portal-block">
              <h4 className="portal-heading">{t('portals.heading')}</h4>
              <ul className="portal-list">
                {portalRows.map((row, idx) => (
                  <li key={`${row.item_id}-${idx}`}>
                    <a href={row.indicator_url || row.source_url} target="_blank" rel="noreferrer">
                      {row.source_label}
                    </a>
                    {row.status === 'discontinued' && <span className="portal-flag"> {t('portals.discontinued')}</span>}
                    <div className="text-muted portal-note">{row.theme}</div>
                  </li>
                ))}
              </ul>
            </div>
          )}

        </div>
      )
    }
    return null
  }

  return (
    <div className="soep-view fade-in" style={{ display: 'flex', flexDirection: 'column', height: '100%', gap: '1rem' }}>
      <div className="analysis-header">
        <p className="analysis-blurb text-muted">{headerBlurb}</p>
        {chatHistory.length > 0 && (
          <button
            className="btn-back"
            onClick={() => {
              setChatHistory([])
              localStorage.removeItem(STORAGE_KEY)
            }}
          >
            {t('action.clear')}
          </button>
        )}
      </div>

      <div className="two-col-body">
        <div className="left-col">
          <div className="filter-panel glass-panel">
        {(filterOptions?.sources || []).length > 1 && (
          <FacetChecks
            label={t('filter.source')}
            /* The API's source list carries an "all" pseudo-entry for the old dropdown. As one
               checkbox among many it would mean nothing, and leaving nothing checked already
               means every source. */
            options={(filterOptions?.sources || [])
              .filter((source) => source.value !== 'all')
              .map((source) => ({ value: source.value, label: sourceOptionLabel(source) }))}
            selected={filters.dataset_scope}
            onToggle={(value) => toggleFilter('dataset_scope', value)}
            onClear={() => clearFilter('dataset_scope')}
            allLabel={t('filter.allSelected')}
            emptyHint={t('filter.noneAvailable')}
            closeLabel={t('filter.close')}
          />
        )}
        <FacetChecks
          label={isInkar ? t('filter.datasetGeo') : t('filter.datasetSoep')}
          options={(filterOptions?.datasets || []).map((dataset) => ({
            value: dataset, label: datasetOptionLabel(dataset), title: dataset,
          }))}
          selected={filters.dataset_label}
          onToggle={(value) => toggleFilter('dataset_label', value)}
          onClear={() => clearFilter('dataset_label')}
          allLabel={t('filter.allSelected')}
          emptyHint={t('filter.noneAvailable')}
          closeLabel={t('filter.close')}
        />
        {showSoepFilters && (filterOptions?.sample_groups || []).length > 0 && (
          <FacetChecks
            label={t('filter.sampleGroup')}
            options={(filterOptions?.sample_groups || []).map((g) => ({
              value: g.value, label: sampleOptionLabel(g),
            }))}
            selected={filters.sample_group}
            onToggle={(value) => toggleFilter('sample_group', value)}
            onClear={() => clearFilter('sample_group')}
            allLabel={t('filter.allSelected')}
            emptyHint={t('filter.noneAvailable')}
            closeLabel={t('filter.close')}
          />
        )}
        {showRegionalFilters && (
          <FacetChecks
            label={t('filter.spatialLevel')}
            options={sortSpatialLevels(filterOptions?.spatial_levels).map((level) => ({
              value: level, label: spatialLevelLabel(level),
            }))}
            selected={filters.spatial_level}
            onToggle={(value) => toggleFilter('spatial_level', value)}
            onClear={() => clearFilter('spatial_level')}
            allLabel={t('filter.allSelected')}
            emptyHint={t('filter.noneAvailable')}
            closeLabel={t('filter.close')}
          />
        )}
        {/* Theme is no longer INKAR-only: SOEP v41 brings the official topic hierarchy, so the
            facet is shown whenever the loaded sources actually offer themes. */}
        {(filterOptions?.themes || []).length > 0 && (
          <FacetChecks
            label={t('filter.theme')}
            /* SOEP topic paths are long and their last segments are what distinguishes them, so
               the list shows the tail and the full path stays in the tooltip. */
            options={(filterOptions?.themes || []).map((theme) => ({
              value: theme, label: shortenPath(theme), title: theme,
            }))}
            selected={filters.theme}
            onToggle={(value) => toggleFilter('theme', value)}
            onClear={() => clearFilter('theme')}
            allLabel={t('filter.allSelected')}
            emptyHint={t('filter.noneAvailable')}
            closeLabel={t('filter.close')}
          />
        )}
        <div>
          <label>{t('filter.startYear')}</label>
          <input
            type="number"
            min={filterOptions?.year_min || 1900}
            max={filterOptions?.year_max || 2100}
            placeholder={filterOptions?.year_min || t('filter.any')}
            value={filters.year_start}
            onChange={(e) => updateFilter('year_start', e.target.value)}
          />
        </div>
        <div>
          <label>{t('filter.endYear')}</label>
          <input
            type="number"
            min={filterOptions?.year_min || 1900}
            max={filterOptions?.year_max || 2100}
            placeholder={filterOptions?.year_max || t('filter.any')}
            value={filters.year_end}
            onChange={(e) => updateFilter('year_end', e.target.value)}
          />
        </div>
        <div>
          <label>{t('filter.topK')}</label>
          <input
            type="number"
            min="3"
            max="30"
            value={filters.top_k}
            onChange={(e) => updateFilter('top_k', e.target.value)}
          />
        </div>
        {showRegionalFilters && (
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={filters.regional_only}
              onChange={(e) => updateFilter('regional_only', e.target.checked)}
            />
            {t('filter.regionalOnly')}
          </label>
        )}
        {/* SOEP v41 publishes most of its variables in the raw questionnaire files. They are
            indexed but hidden by default, as a switch the user can see and undo rather than a
            silent penalty in the ranking. */}
        {showSoepFilters && (filterOptions?.raw_rows || 0) > 0 && (
          <label className="checkbox-row" title={t('filter.includeRawTitle')}>
            <input
              type="checkbox"
              checked={filters.include_raw}
              onChange={(e) => updateFilter('include_raw', e.target.checked)}
            />
            {t('filter.includeRaw', { count: filterOptions.raw_rows.toLocaleString(language === 'de' ? 'de-DE' : 'en-GB') })}
          </label>
        )}
          {droppedFilters.length > 0 && (
            <p className="filter-dropped">
              {t('filter.dropped', { values: droppedFilters.join(', ') })}
            </p>
          )}
          <div className="filter-note">
            {t('filter.active', { source: sourceLabel })}
            {filterOptions?.year_min && filterOptions?.year_max && ` | ${t('filter.years', { min: filterOptions.year_min, max: filterOptions.year_max })}`}
            {filterOptions?.index_built && ` | ${t('filter.indexBuilt', { date: filterOptions.index_built })}`}
          </div>
          </div>

          <div className="chat-section glass-panel">
            <form onSubmit={handleAsk} style={{ display: 'grid', gap: '0.75rem' }}>
              <textarea
                className="chat-input"
                rows={6}
                style={{ resize: 'vertical', minHeight: '140px', maxHeight: '340px' }}
                placeholder={t(isInkar ? 'placeholder.inkar' : isSoep ? 'placeholder.soep' : 'placeholder.all')}
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                onKeyDown={handleKeyDown}
              />
              <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                <button className="btn-primary" type="submit" disabled={loading || !question.trim()}>
                  {loading ? t('action.searching') : t('action.ask')}
                </button>
              </div>
            </form>
          </div>
        </div>

        <div className="right-col">
          <div className="chat-history-container" style={{ paddingRight: '0.5rem' }}>
          {chatHistory.length === 0 ? (
            <p style={{ textAlign: 'center', color: 'var(--muted)', marginTop: '2rem' }}>{t('results.empty')}</p>
          ) : (
            chatHistory.map((msg, i) => (
              <div key={`msg-${i}`} ref={i === chatHistory.length - 1 ? latestMsgRef : null}>
                {renderMessage(msg, i)}
              </div>
            ))
          )}
          {loading && <div className="glass-panel" style={{ padding: '1rem', marginBottom: '1rem' }}><em>{t('results.searching')}</em></div>}
          {error && <div className="error-message">{error}</div>}
          <div ref={messagesEndRef} />
          </div>
        </div>
      </div>

      <div className="cite-footer text-muted">
        {t('cite.prefix', { title: cite.title })}{' '}
        <a href={`https://doi.org/${cite.doi}`} target="_blank" rel="noreferrer">doi.org/{cite.doi}</a>
        {/* Imprint, privacy statement and the attribution list moved into the page footer on
            2026-09-09, where the project site keeps them too; repeating them here would put the
            same four links twice on one page. */}
      </div>
    </div>
  )
}

export default SOEPRagAdvisor
