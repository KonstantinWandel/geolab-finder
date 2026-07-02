import { useEffect, useMemo, useRef, useState } from 'react'

function SOEPRagAdvisor({ apiUrl, mode = 'all' }) {
  const isInkar = mode === 'inkar'
  const isSoep = mode === 'soep'
  const isAll = mode === 'all'
  const showRegionalFilters = isInkar || isAll
  const STORAGE_KEY = `geolab_history_${mode}`
  const headerTitle = isInkar
    ? 'INKAR Regional Indicator Finder'
    : isSoep
    ? 'SOEP Variable Finder'
    : 'GeoLAB Metadata Advisor'
  const headerBlurb = isInkar
    ? 'Semantic search over INKAR 2025 regional indicators — filter by spatial level, theme and year.'
    : isSoep
    ? 'Multilingual semantic search over SOEP-Core variable metadata.'
    : 'Semantic search over SOEP variables and INKAR regional indicators.'

  // INKAR spatial levels: one concept, shown with its German name + NUTS/LAU alias.
  const SPATIAL_LEVEL_LABELS = {
    Gemeinden: 'Municipality (Gemeinde / LAU)',
    Kreise: 'District (Kreis / NUTS3)',
    NUTS2: 'NUTS2 region',
  }

  const [question, setQuestion] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [filterOptions, setFilterOptions] = useState(null)
  const [filters, setFilters] = useState({
    dataset_scope: isAll ? 'all' : mode,
    dataset_label: 'All datasets',
    nuts_level: 'Any',
    spatial_level: 'Any',
    theme: 'Any',
    year_start: '',
    year_end: '',
    regional_only: false,
    top_k: 12,
  })

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

  useEffect(() => {
    let cancelled = false
    async function loadFilterOptions() {
      try {
        const res = await fetch(`${apiUrl}/soep/filter-options`)
        if (!res.ok) return
        const data = await res.json()
        if (!cancelled) setFilterOptions(data)
      } catch (e) {
        console.error(e)
      }
    }
    loadFilterOptions()
    return () => {
      cancelled = true
    }
  }, [apiUrl])

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
          dataset_scope: isAll ? filterSnapshot.dataset_scope : mode,
          dataset_label: filterSnapshot.dataset_label === 'All datasets' ? null : filterSnapshot.dataset_label,
          nuts_level: filterSnapshot.nuts_level === 'Any' ? null : filterSnapshot.nuts_level,
          spatial_level: filterSnapshot.spatial_level === 'Any' ? null : filterSnapshot.spatial_level,
          theme: filterSnapshot.theme === 'Any' ? null : filterSnapshot.theme,
          year_start: filterSnapshot.year_start ? Number(filterSnapshot.year_start) : null,
          year_end: filterSnapshot.year_end ? Number(filterSnapshot.year_end) : null,
          regional_only: Boolean(filterSnapshot.regional_only),
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
      const rows = result.recommended_variables || []
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

          <div className="table-scroll metadata-table">
            <table>
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
                      {row.source_key === 'inkar' && row.theme && <div className="mini-chip">{row.theme}</div>}
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
                      <details style={{ maxWidth: '420px', cursor: 'pointer' }}>
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
        {isAll && (
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
          <label>{isInkar ? 'INKAR sheet' : 'SOEP dataset'}</label>
          <select value={filters.dataset_label} onChange={(e) => updateFilter('dataset_label', e.target.value)}>
            <option value="All datasets">{isInkar ? 'All sheets' : 'All datasets'}</option>
            {(filterOptions?.datasets || []).map((dataset) => (
              <option key={dataset} value={dataset}>{dataset}</option>
            ))}
          </select>
        </div>
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
            <div>
              <label>INKAR theme</label>
              <select value={filters.theme} onChange={(e) => updateFilter('theme', e.target.value)}>
                <option>Any</option>
                {(filterOptions?.themes || []).map((theme) => (
                  <option key={theme} value={theme}>{theme}</option>
                ))}
              </select>
            </div>
          </>
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
          <div className="filter-note">
            Active: {sourceLabel}
            {filterOptions?.year_min && filterOptions?.year_max && ` | indexed years ${filterOptions.year_min}-${filterOptions.year_max}`}
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
    </div>
  )
}

export default SOEPRagAdvisor
