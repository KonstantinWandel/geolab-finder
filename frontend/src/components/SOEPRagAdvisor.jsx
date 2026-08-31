import { useEffect, useMemo, useRef, useState } from 'react'
import { makeTranslator, shortenPath, datasetLabel, sortSpatialLevels } from '../i18n'

// The project site carries the imprint, the privacy statement and the attribution list.
const GEOLAB_SITE = 'https://lwc-soep-regiohub.pages.ub.uni-bielefeld.de/geolab'

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
  const [filters, setFilters] = useState({
    // The regional finder serves many sources now, so only the SOEP deployment
    // pre-selects its own source; everywhere else the default is every source.
    dataset_scope: isSoep ? 'soep' : 'all',
    dataset_label: 'All datasets',
    nuts_level: 'Any',
    spatial_level: 'Any',
    theme: 'Any',
    year_start: '',
    year_end: '',
    regional_only: false,
    include_raw: false,
    sample_group: 'Any',
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
        if (filters.dataset_scope && filters.dataset_scope !== 'all') query.set('source', filters.dataset_scope)
        if (filters.include_raw) query.set('include_raw', 'true')
        const suffix = query.toString() ? `?${query}` : ''
        const res = await fetch(`${apiUrl}/soep/filter-options${suffix}`)
        if (!res.ok) return
        const data = await res.json()
        if (cancelled) return
        setFilterOptions(data)
        setFilters((current) => {
          const next = { ...current }
          if (next.dataset_label !== 'All datasets' && !(data.datasets || []).includes(next.dataset_label)) {
            next.dataset_label = 'All datasets'
          }
          if (next.theme !== 'Any' && !(data.themes || []).includes(next.theme)) next.theme = 'Any'
          if (next.spatial_level !== 'Any' && !(data.spatial_levels || []).includes(next.spatial_level)) {
            next.spatial_level = 'Any'
          }
          if (next.nuts_level !== 'Any' && !(data.nuts_levels || []).includes(next.nuts_level)) {
            next.nuts_level = 'Any'
          }
          return next
        })
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
    const source = filterOptions?.sources?.find((item) => item.value === filters.dataset_scope)
    return source ? sourceOptionLabel(source) : t('filter.allSources')
  }, [filterOptions, filters.dataset_scope, language])

  const updateFilter = (key, value) => {
    setFilters((current) => ({ ...current, [key]: value }))
  }

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
          dataset_scope: filterSnapshot.dataset_scope || 'all',
          dataset_label: filterSnapshot.dataset_label === 'All datasets' ? null : filterSnapshot.dataset_label,
          nuts_level: filterSnapshot.nuts_level === 'Any' ? null : filterSnapshot.nuts_level,
          spatial_level: filterSnapshot.spatial_level === 'Any' ? null : filterSnapshot.spatial_level,
          theme: filterSnapshot.theme === 'Any' ? null : filterSnapshot.theme,
          year_start: filterSnapshot.year_start ? Number(filterSnapshot.year_start) : null,
          year_end: filterSnapshot.year_end ? Number(filterSnapshot.year_end) : null,
          regional_only: Boolean(filterSnapshot.regional_only),
          include_raw: Boolean(filterSnapshot.include_raw),
          sample_groups: filterSnapshot.sample_group === 'Any' ? null : [filterSnapshot.sample_group],
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

  const renderMessage = (msg, i) => {
    if (msg.role === 'user') {
      return (
        <div key={i} className="glass-panel" style={{ padding: '1rem', marginBottom: '1rem', background: 'var(--surface-2)' }}>
          <strong>{t('chat.you')}</strong>
          <p style={{ whiteSpace: 'pre-wrap', margin: '0.5rem 0 0 0' }}>{msg.content}</p>
          {msg.filters && (
            <p className="text-muted" style={{ fontSize: '0.8rem', margin: '0.5rem 0 0 0' }}>
              {t('chat.filters', { summary: [msg.filters.dataset_scope, msg.filters.dataset_label, msg.filters.nuts_level, msg.filters.spatial_level, `${msg.filters.year_start || t('filter.any')}-${msg.filters.year_end || t('filter.any')}`].join(', ') })}
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
          <div>
            <label>{t('filter.source')}</label>
            <select value={filters.dataset_scope} onChange={(e) => updateFilter('dataset_scope', e.target.value)}>
              {(filterOptions?.sources || [{ value: 'all', label: t('filter.allSources') }]).map((source) => (
                <option key={source.value} value={source.value}>{sourceOptionLabel(source)}</option>
              ))}
            </select>
          </div>
        )}
        <div>
          <label>{isInkar ? t('filter.datasetGeo') : t('filter.datasetSoep')}</label>
          <select value={filters.dataset_label} onChange={(e) => updateFilter('dataset_label', e.target.value)}>
            <option value="All datasets">{t('filter.allDatasets')}</option>
            {(filterOptions?.datasets || []).map((dataset) => (
              <option key={dataset} value={dataset}>{datasetOptionLabel(dataset)}</option>
            ))}
          </select>
        </div>
        {showSoepFilters && (filterOptions?.sample_groups || []).length > 0 && (
          <div>
            <label>{t('filter.sampleGroup')}</label>
            <select value={filters.sample_group} onChange={(e) => updateFilter('sample_group', e.target.value)}>
              <option value="Any">{t('filter.anySampleGroup')}</option>
              {(filterOptions?.sample_groups || []).map((g) => (
                <option key={g.value} value={g.value}>{sampleOptionLabel(g)}</option>
              ))}
            </select>
          </div>
        )}
        {showRegionalFilters && (
          <>
            <div>
              <label>{t('filter.spatialLevel')}</label>
              <select value={filters.spatial_level} onChange={(e) => updateFilter('spatial_level', e.target.value)}>
                <option value="Any">{t('filter.anyLevel')}</option>
                {sortSpatialLevels(filterOptions?.spatial_levels).map((level) => (
                  <option key={level} value={level}>{spatialLevelLabel(level)}</option>
                ))}
              </select>
            </div>
          </>
        )}
        {/* Theme is no longer INKAR-only: SOEP v41 brings the official topic hierarchy, so the
            facet is shown whenever the loaded sources actually offer themes. */}
        {(filterOptions?.themes || []).length > 0 && (
          <div>
            <label>{t('filter.theme')}</label>
            <select value={filters.theme} onChange={(e) => updateFilter('theme', e.target.value)}>
              <option value="Any">{t('filter.any')}</option>
              {/* SOEP topic paths are long, and a truncated dropdown made different paths look
                  identical; the last segments are what distinguishes them. */}
              {(filterOptions?.themes || []).map((theme) => (
                <option key={theme} value={theme} title={theme}>{shortenPath(theme)}</option>
              ))}
            </select>
          </div>
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
        {/* The service is public, so the imprint, the privacy statement and the attribution
            list of every indexed source have to be reachable from every page. */}
        <div className="legal-links">
          <a href={`${GEOLAB_SITE}/imprint.html`} target="_blank" rel="noreferrer">{t('legal.imprint')}</a>
          <a href={`${GEOLAB_SITE}/privacy.html`} target="_blank" rel="noreferrer">{t('legal.privacy')}</a>
          <a href={`${GEOLAB_SITE}/data-sources.html`} target="_blank" rel="noreferrer">{t('legal.sources')}</a>
          <a href={GEOLAB_SITE} target="_blank" rel="noreferrer">GeoLAB</a>
        </div>
      </div>
    </div>
  )
}

export default SOEPRagAdvisor
