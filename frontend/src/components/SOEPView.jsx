import { useState } from 'react'

function SOEPView({ onBack, apiUrl }) {
    const [searchTerm, setSearchTerm] = useState('')
    const [searchResults, setSearchResults] = useState([])
    const [selectedVar, setSelectedVar] = useState(null)
    const [year, setYear] = useState(2019)
    const [loading, setLoading] = useState(false)
    const [result, setResult] = useState(null)
    const [error, setError] = useState(null)

    const handleSearch = async (e) => {
        e.preventDefault()
        try {
            const res = await fetch(`${apiUrl}/search_soep?q=${searchTerm}`)
            const data = await res.json()
            setSearchResults(data)
        } catch (err) {
            console.error(err)
        }
    }

    const handleAggregate = async (variableCode) => {
        setLoading(true)
        setError(null)
        setResult(null)

        // Find dataset info from search results to display if needed
        const varInfo = searchResults.find(r => r.code === variableCode)

        try {
            const res = await fetch(`${apiUrl}/soep`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ variable: variableCode, year: parseInt(year) })
            })
            const data = await res.json()
            if (data.error) throw new Error(data.error)
            setResult(data.data)
            setSelectedVar(varInfo) // Keep track of what we aggregated
        } catch (err) {
            setError(err.message)
        } finally {
            setLoading(false)
        }
    }

    return (
        <div className="soep-view fade-in">
            <button onClick={onBack} className="btn-back">← Back to Search</button>

            <div className="analysis-header glass-panel">
                <h2>SOEP Integration (v37)</h2>
                <p className="text-muted">Semantic Search & Regional Aggregation</p>
            </div>

            <div className="main-content-split">
                {/* LEFT: Search & List */}
                <div className="chat-section glass-panel">
                    <form onSubmit={handleSearch} style={{ display: 'flex', gap: '0.5rem' }}>
                        <input
                            className="chat-input"
                            value={searchTerm}
                            onChange={(e) => setSearchTerm(e.target.value)}
                            placeholder="Search (e.g. Income, Satisfaction)..."
                        />
                        <button type="submit" className="btn-primary">Search</button>
                    </form>

                    <div className="results-list" style={{ marginTop: '1rem', overflowY: 'auto' }}>
                        {searchResults.map((item) => (
                            <div key={item.code} className="result-card" style={{ padding: '0.8rem', background: 'rgba(255,255,255,0.05)', marginBottom: '0.5rem' }}>
                                <div style={{ fontWeight: 'bold', color: '#60a5fa' }}>{item.label}</div>
                                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem', color: '#94a3b8', marginTop: '0.3rem' }}>
                                    <span>{item.code} ({item.dataset})</span>
                                    <span>{item.years}</span>
                                </div>
                                <div style={{ marginTop: '0.5rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                    <label style={{ fontSize: '0.8rem' }}>Year:</label>
                                    <input
                                        type="number"
                                        value={year}
                                        onChange={(e) => setYear(e.target.value)}
                                        style={{ width: '60px', padding: '2px', background: 'black', color: 'white', border: '1px solid #333' }}
                                    />
                                    <button
                                        className="btn-primary"
                                        style={{ padding: '0.3rem 0.8rem', fontSize: '0.8rem' }}
                                        onClick={() => handleAggregate(item.code)}
                                        disabled={loading}
                                    >
                                        Aggregate
                                    </button>
                                </div>
                            </div>
                        ))}
                    </div>
                </div>

                {/* RIGHT: Results */}
                <div className="workspace-section">
                    {!result && !error && (
                        <div className="empty-state">
                            Select a variable on the left to aggregate it by Bundesland.
                        </div>
                    )}

                    {error && <div className="error-message">{error}</div>}

                    {result && (
                        <div className="execution-result glass-panel">
                            <h3>
                                Aggregation: {selectedVar ? selectedVar.label : 'Result'} ({year})
                            </h3>

                            <div className="table-scroll">
                                <table>
                                    <thead>
                                        <tr>
                                            <th>Region</th>
                                            <th>Value (Mean)</th>
                                            <th>N (Sample)</th>
                                            <th>Source</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {result.map((row, i) => (
                                            <tr key={i}>
                                                <td>{row.spatial_name} ({row.spatial_id})</td>
                                                <td>
                                                    <span style={{ color: '#10b981', fontWeight: 'bold' }}>
                                                        {typeof row.value === 'number' ? row.value.toFixed(2) : row.value}
                                                    </span>
                                                </td>
                                                <td>{row.sample_size}</td>
                                                <td style={{ fontSize: '0.8rem', color: '#64748b' }}>{row.source_original}</td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </div>
    )
}

export default SOEPView
