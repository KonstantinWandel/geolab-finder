import { useEffect, useMemo, useRef, useState } from 'react'

// The project site carries the imprint, the privacy statement and the attribution list.
const GEOLAB_SITE = 'https://lwc-soep-regiohub.pages.ub.uni-bielefeld.de/geolab'

function SOEPRagAdvisor({ apiUrl, mode = 'all' }) {
  const isInkar = mode === 'inkar'
  const isSoep = mode === 'soep'
  const isAll = mode === 'all'
  const showRegionalFilters = isInkar || isAll
  const showSoepFilters = isSoep || isAll
  const STORAGE_KEY = `geolab_history_${mode}`
  const headerTitle = isInkar
    ? 'GeoDB Regional Data Finder'
    : isSoep
    ? 'SOEP Variable Finder'
    : 'GeoLAB Metadata Advisor'
  const headerBlurb = isInkar
    ? 'Semantic search across German georeferenced data sources. Describe the concept you need data on; every hit links out to the source that holds it, and says how precisely that link lands.'
    : isSoep
    ? 'Multilingual semantic search over SOEP-Core variable metadata.'
    : 'Semantic search over SOEP variables and INKAR regional indicators.'

  // Spatial levels: one concept, shown with its German name + NUTS/LAU alias.
  const SPATIAL_LEVEL_LABELS = {
    Gemeinden: 'Municipality (Gemeinde / LAU)',
    Kreise: 'District (Kreis / NUTS3)',
    NUTS2: 'NUTS2 region',
    'Bundesländer': 'Federal state (Bundesland / NUTS1)',
    Regierungsbezirke: 'Government region (Regierungsbezirk)',
    Bezirke: 'Borough (Bezirk)',
    Ortsteile: 'Locality (Ortsteil / Bezirksregion)',
    PLZ: 'Postcode (PLZ)',
    'Adressen/Koordinaten': 'Address / coordinates',
    Bundestagswahlkreise: 'Federal constituency (Wahlkreis)',
    'Weitere Gliederungen': 'Other spatial breakdowns',
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
  const LINK_LEVEL = {
    indicator: { label: 'opens the indicator', short: 'indicator link' },
    table: { label: 'opens the exact table', short: 'table link' },
    statistic: { label: 'opens the statistic that contains it', short: 'statistic link' },
    dataset: { label: 'opens the dataset that contains it', short: 'dataset link' },
    portal: { label: 'opens the portal; search from there', short: 'portal link' },
  }

  // Human label for a SOEP sample/questionnaire group key (from the fetched facet).
  const sampleGroupLabel = (key) =>
    (filterOptions?.sample_groups || []).find((g) => g.value === key)?.label || null

  const [chatHistory, setChatHistory] = useState([])
  const [selectedRows, setSelectedRows] = useState({})
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
        const scope = filters.dataset_scope && filters.dataset_scope !== 'all'
          ? `?source=${encodeURIComponent(filters.dataset_scope)}`
          : ''
        const res = await fetch(`${apiUrl}/soep/filter-options${scope}`)
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
  }, [apiUrl, filters.dataset_scope])

  useEffect(() => {
    // Keep the TOP of the newest answer (the most relevant results) in view,
    // instead of jumping to the bottom of the results list.
    latestMsgRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [chatHistory])

  const sourceLabel = useMemo(() => {
    const source = filterOptions?.sources?.find((item) => item.value === filters.dataset_scope)
    return source?.label || 'All metadata sources'
  }, [filterOptions, filters.dataset_scope])

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

  const renderSourceLink = (row) => {
    const href = row.source_url || row.selector_url || row.indicator_url
    if (!href) return <span className="text-muted">No link</span>
    const label = row.source_key === 'inkar' ? 'INKAR' : 'codebook'
    return (
      <a href={href} target="_blank" rel="noreferrer" style={{ color: 'var(--accent)' }}>
        {label}
      </a>
    )
  }

  const renderMessage = (msg, i) => {
    if (msg.role === 'user') {
      return (
        <div key={i} className="glass-panel" style={{ padding: '1rem', marginBottom: '1rem', background: 'var(--surface-2)' }}>
          <strong>You:</strong>
          <p style={{ whiteSpace: 'pre-wrap', margin: '0.5rem 0 0 0' }}>{msg.content}</p>
          {msg.filters && (
            <p className="text-muted" style={{ fontSize: '0.8rem', margin: '0.5rem 0 0 0' }}>
              Filters: {msg.filters.dataset_scope}, {msg.filters.dataset_label}, {msg.filters.nuts_level}, {msg.filters.spatial_level}, {msg.filters.year_start || 'any'}-{msg.filters.year_end || 'any'}
            </p>
          )}
        </div>
      )
    }
    if (msg.role === 'error') {
      return (
        <div key={i} className="error-message" style={{ marginBottom: '1rem' }}>
          Error: {msg.content}
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
      const selectedCount = rows.filter((row, idx) => selectedRows[`${i}:${row.item_id || row.variable_name || idx}`]).length
      return (
        <div key={i} className="execution-result glass-panel" style={{ marginBottom: '1.5rem', padding: '1rem' }}>
          <div className="results-toolbar">
            <h3 style={{ margin: 0 }}>Results</h3>
            <div className="export-actions">
              <span className="text-muted">{selectedCount ? `${selectedCount} selected` : 'Export all rows'}</span>
              <button type="button" className="btn-secondary" onClick={() => exportRows(rows, 'csv', i)}>CSV</button>
              <button type="button" className="btn-secondary" onClick={() => exportRows(rows, 'json', i)}>JSON</button>
            </div>
          </div>
          <p style={{ fontSize: '0.85rem', color: 'var(--muted)', marginTop: '0.6rem' }}>
            Retrieval: {result.embedding_model} | Generator: {result.llm_model || 'disabled'} | Mode: {result.response_mode || 'retrieval-only'} | Index: {result.index_type}
          </p>

          {rows.length === 0 && portalRows.length > 0 && (
            <p className="text-muted" style={{ marginTop: '0.4rem' }}>
              No indicator-level hit for this question. The portals below are the places to look.
            </p>
          )}
          <div className="table-scroll metadata-table">
            <table className="results-table">
              <thead>
                <tr>
                  <th>Select</th>
                  <th>Record</th>
                  <th>Source</th>
                  <th>Score</th>
                  <th>Coverage</th>
                  <th>Why useful</th>
                  <th>Get it from</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row, idx) => (
                  <tr key={`${row.item_id || row.variable_name}-${idx}`}>
                    <td>
                      <input
                        type="checkbox"
                        checked={Boolean(selectedRows[`${i}:${row.item_id || row.variable_name || idx}`])}
                        onChange={() => toggleRow(i, row, idx)}
                        aria-label={`Select ${row.variable_name || row.label || 'row'}`}
                      />
                    </td>
                    <td>
                      <div style={{ fontWeight: 'bold' }}>{row.variable_name}</div>
                      <div style={{ fontSize: '0.85rem', color: 'var(--muted)' }}>{row.label}</div>
                      {row.source_key !== 'soep' && row.theme && <div className="mini-chip">{row.theme}</div>}
                      {row.link_level && LINK_LEVEL[row.link_level] && (
                        <div
                          className="mini-chip"
                          title={row.link_verified === false
                            ? `${LINK_LEVEL[row.link_level].label} (documented form; the target portal is a JavaScript app, so the link could not be verified server-side)`
                            : LINK_LEVEL[row.link_level].label}
                        >
                          {LINK_LEVEL[row.link_level].short}{row.link_verified === false ? '*' : ''}
                        </div>
                      )}
                      {row.source_key === 'soep' && sampleGroupLabel(row.sample_group) && (
                        <div className="mini-chip">{sampleGroupLabel(row.sample_group)}</div>
                      )}
                      {row.also_in_datasets?.length > 0 && (
                        <div className="text-muted" style={{ fontSize: '0.8rem', marginTop: '2px' }}>
                          also in: {row.also_in_datasets.join(', ')}
                        </div>
                      )}
                    </td>
                    <td>
                      <div>{row.source_label}</div>
                      <div className="text-muted">{row.dataset_label || row.dataset}</div>
                    </td>
                    <td>{formatScore(row.score)}</td>
                    <td>
                      <div>{row.available_years_text || 'No explicit years'}</div>
                      <div className="text-muted">{(row.nuts_levels || []).join(', ') || (row.spatial_levels || []).join(', ') || 'No spatial level'}</div>
                    </td>
                    <td>
                      <details className="why-useful" style={{ cursor: 'pointer' }}>
                        <summary style={{ fontWeight: 'bold', color: 'var(--accent)', outline: 'none' }}>View extracted context</summary>
                        <div style={{ marginTop: '0.5rem', lineHeight: '1.4', fontSize: '0.9rem', color: 'var(--text-soft)' }}>
                          {row.rich_description || row.stats_summary || row.label || 'No description found.'}
                          {row.api_hint && <p className="text-muted">{row.api_hint}</p>}
                        </div>
                      </details>
                    </td>
                    <td>{renderSourceLink(row)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {portalRows.length > 0 && (
            <div className="portal-block">
              <h4 className="portal-heading">Data portals to search in</h4>
              <ul className="portal-list">
                {portalRows.map((row, idx) => (
                  <li key={`${row.item_id}-${idx}`}>
                    <a href={row.indicator_url || row.source_url} target="_blank" rel="noreferrer">
                      {row.source_label}
                    </a>
                    {row.status === 'discontinued' && <span className="portal-flag"> no longer updated</span>}
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
            Clear
          </button>
        )}
      </div>

      <div className="two-col-body">
        <div className="left-col">
          <div className="filter-panel glass-panel">
        {(filterOptions?.sources || []).length > 1 && (
          <div>
            <label>Search source</label>
            <select value={filters.dataset_scope} onChange={(e) => updateFilter('dataset_scope', e.target.value)}>
              {(filterOptions?.sources || [{ value: 'all', label: 'All metadata sources' }]).map((source) => (
                <option key={source.value} value={source.value}>{source.label}</option>
              ))}
            </select>
          </div>
        )}
        <div>
          <label>{isInkar ? 'Dataset / sheet' : 'SOEP dataset'}</label>
          <select value={filters.dataset_label} onChange={(e) => updateFilter('dataset_label', e.target.value)}>
            <option value="All datasets">All datasets</option>
            {(filterOptions?.datasets || []).map((dataset) => (
              <option key={dataset} value={dataset}>{dataset}</option>
            ))}
          </select>
        </div>
        {showSoepFilters && (filterOptions?.sample_groups || []).length > 0 && (
          <div>
            <label>Sample / questionnaire</label>
            <select value={filters.sample_group} onChange={(e) => updateFilter('sample_group', e.target.value)}>
              <option value="Any">Any sample / questionnaire</option>
              {(filterOptions?.sample_groups || []).map((g) => (
                <option key={g.value} value={g.value}>{g.label}</option>
              ))}
            </select>
          </div>
        )}
        {showRegionalFilters && (
          <>
            <div>
              <label>Spatial level</label>
              <select value={filters.spatial_level} onChange={(e) => updateFilter('spatial_level', e.target.value)}>
                <option value="Any">Any level</option>
                {(filterOptions?.spatial_levels || []).map((level) => (
                  <option key={level} value={level}>{SPATIAL_LEVEL_LABELS[level] || level}</option>
                ))}
              </select>
            </div>
          </>
        )}
        {/* Theme is no longer INKAR-only: SOEP v41 brings the official topic hierarchy, so the
            facet is shown whenever the loaded sources actually offer themes. */}
        {(filterOptions?.themes || []).length > 0 && (
          <div>
            <label>Theme</label>
            <select value={filters.theme} onChange={(e) => updateFilter('theme', e.target.value)}>
              <option>Any</option>
              {(filterOptions?.themes || []).map((theme) => (
                <option key={theme} value={theme}>{theme}</option>
              ))}
            </select>
          </div>
        )}
        <div>
          <label>Start year</label>
          <input
            type="number"
            min={filterOptions?.year_min || 1900}
            max={filterOptions?.year_max || 2100}
            placeholder={filterOptions?.year_min || 'Any'}
            value={filters.year_start}
            onChange={(e) => updateFilter('year_start', e.target.value)}
          />
        </div>
        <div>
          <label>End year</label>
          <input
            type="number"
            min={filterOptions?.year_min || 1900}
            max={filterOptions?.year_max || 2100}
            placeholder={filterOptions?.year_max || 'Any'}
            value={filters.year_end}
            onChange={(e) => updateFilter('year_end', e.target.value)}
          />
        </div>
        <div>
          <label>Returned records</label>
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
            Regionalized only
          </label>
        )}
        {/* SOEP v41 publishes most of its variables in the raw questionnaire files. They are
            indexed but hidden by default, as a switch the user can see and undo rather than a
            silent penalty in the ranking. */}
        {showSoepFilters && (filterOptions?.raw_rows || 0) > 0 && (
          <label className="checkbox-row" title="soepdata/raw: the raw questionnaire files behind the analysis datasets">
            <input
              type="checkbox"
              checked={filters.include_raw}
              onChange={(e) => updateFilter('include_raw', e.target.checked)}
            />
            Include raw questionnaire files ({filterOptions.raw_rows.toLocaleString()})
          </label>
        )}
          <div className="filter-note">
            Active: {sourceLabel}
            {filterOptions?.year_min && filterOptions?.year_max && ` | indexed years ${filterOptions.year_min}-${filterOptions.year_max}`}
            {filterOptions?.index_built && ` | index as of ${filterOptions.index_built}`}
          </div>
          </div>

          <div className="chat-section glass-panel">
            <form onSubmit={handleAsk} style={{ display: 'grid', gap: '0.75rem' }}>
              <textarea
                className="chat-input"
                rows={6}
                style={{ resize: 'vertical', minHeight: '140px', maxHeight: '340px' }}
                placeholder={isInkar
                  ? 'Example: regional indicators for rural infrastructure, employment, childcare, or commuting (Shift+Enter for new line)'
                  : isSoep
                  ? 'Example: net individual income from labour; household equivalised income; years of education (Shift+Enter for new line)'
                  : 'Example: net labour income and regional childcare coverage by district (Shift+Enter for new line)'}
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                onKeyDown={handleKeyDown}
              />
              <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                <button className="btn-primary" type="submit" disabled={loading || !question.trim()}>
                  {loading ? 'Searching...' : 'Ask'}
                </button>
              </div>
            </form>
          </div>
        </div>

        <div className="right-col">
          <div className="chat-history-container" style={{ paddingRight: '0.5rem' }}>
          {chatHistory.length === 0 ? (
            <p style={{ textAlign: 'center', color: 'var(--muted)', marginTop: '2rem' }}>No results yet. Enter a query on the left.</p>
          ) : (
            chatHistory.map((msg, i) => (
              <div key={`msg-${i}`} ref={i === chatHistory.length - 1 ? latestMsgRef : null}>
                {renderMessage(msg, i)}
              </div>
            ))
          )}
          {loading && <div className="glass-panel" style={{ padding: '1rem', marginBottom: '1rem' }}><em>Searching semantic metadata index...</em></div>}
          {error && <div className="error-message">{error}</div>}
          <div ref={messagesEndRef} />
          </div>
        </div>
      </div>

      <div className="cite-footer text-muted">
        Please cite: Wandel, K. (2026). {cite.title}. Zenodo.{' '}
        <a href={`https://doi.org/${cite.doi}`} target="_blank" rel="noreferrer">doi.org/{cite.doi}</a>
        {/* The service is public, so the imprint, the privacy statement and the attribution
            list of every indexed source have to be reachable from every page. */}
        <div className="legal-links">
          <a href={`${GEOLAB_SITE}/imprint.html`} target="_blank" rel="noreferrer">Imprint</a>
          <a href={`${GEOLAB_SITE}/privacy.html`} target="_blank" rel="noreferrer">Privacy</a>
          <a href={`${GEOLAB_SITE}/data-sources.html`} target="_blank" rel="noreferrer">Data sources and attribution</a>
          <a href={GEOLAB_SITE} target="_blank" rel="noreferrer">GeoLAB</a>
        </div>
      </div>
    </div>
  )
}

export default SOEPRagAdvisor
