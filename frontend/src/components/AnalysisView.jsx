import { useState, useEffect, useRef } from 'react'
// Removed react-markdown to avoid build errors

function AnalysisView({ table, onBack, apiUrl }) {
    const [query, setQuery] = useState('')
    const [loading, setLoading] = useState(false)
    const [executing, setExecuting] = useState(false)
    const [analysis, setAnalysis] = useState(null) // { sql_or_code: str, explanation: str, type: str, result: [] }
    const [error, setError] = useState(null)
    const [executionResult, setExecutionResult] = useState(null) // { success: bool, stdout: str, data: any }

    // Auto-scroll chat
    const messagesEndRef = useRef(null)

    // Scroll to bottom when messages change
    useEffect(() => {
        if (messagesEndRef.current) {
            messagesEndRef.current.scrollIntoView({ behavior: "smooth" })
        }
    }, [analysis, error, loading])

    const handleAnalyze = async (e) => {
        e.preventDefault()
        if (!query.trim()) return

        setLoading(true)
        setError(null)
        setAnalysis(null)
        setExecutionResult(null)

        try {
            const res = await fetch(`${apiUrl}/analyze`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    table_code: table.code,
                    user_query: query
                })
            })
            const data = await res.json()
            if (data.error) throw new Error(data.error)
            setAnalysis(data)
        } catch (err) {
            setError(err.message)
        } finally {
            setLoading(false)
        }
    }

    const handleExecute = async () => {
        if (!analysis || !analysis.sql_or_code) return
        setExecuting(true)
        setExecutionResult(null)

        try {
            const res = await fetch(`${apiUrl}/execute`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ code: analysis.sql_or_code })
            })
            const data = await res.json()
            setExecutionResult(data)
        } catch (err) {
            setExecutionResult({ success: false, stderr: err.message })
        } finally {
            setExecuting(false)
        }
    }

    return (
        <div className="analysis-view fade-in">
            <button onClick={onBack} className="btn-back">← Back to Search</button>

            <div className="analysis-header glass-panel">
                <h2>{table.title}</h2>
                <span className="text-muted">Code: {table.code}</span>
            </div>

            {/* Step 1: Query */}
            <div className="chat-section glass-panel">
                <div className="chat-history">
                    <div className="system-message">
                        This agent can generate Python scripts to download this data. What do you need?
                    </div>
                    {analysis && (
                        <div className="agent-message">
                            <strong>Plan:</strong> {analysis.explanation}
                        </div>
                    )}
                    {error && <div className="error-message">{error}</div>}
                    <div ref={messagesEndRef} />
                </div>

                <form onSubmit={handleAnalyze} className="chat-input-area">
                    <input
                        className="chat-input"
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                        placeholder="E.g. Download data for 2023..."
                    />
                    <button type="submit" className="btn-primary" disabled={loading}>
                        {loading ? <span className="spinner"></span> : 'Generate Script'}
                    </button>
                </form>
            </div>

            {/* Step 2: Code */}
            {analysis && (
                <div className="code-viewer glass-panel">
                    <div className="panel-header">
                        <h3>Generated Script</h3>
                        <button
                            className={`btn-run ${executing ? 'running' : ''}`}
                            onClick={handleExecute}
                            disabled={executing}
                        >
                            {executing ? 'Running...' : '▶ Run Code'}
                        </button>
                    </div>
                    <pre className="code-block">
                        <code>{analysis.sql_or_code}</code>
                    </pre>
                </div>
            )}

            {/* Step 3: Result */}
            {executionResult && (
                <div className="execution-result glass-panel">
                    <div className="panel-header">
                        <h3>Execution Output</h3>
                    </div>
                    {executionResult.success ? (
                        <div className="success-output">
                            <pre className="console-output">{executionResult.stdout}</pre>

                            {executionResult.data && (
                                <div className="data-preview">
                                    <h4>Data Preview</h4>
                                    {Array.isArray(executionResult.data) ? (
                                        <div className="table-scroll">
                                            <table>
                                                <thead>
                                                    <tr>
                                                        {Object.keys(executionResult.data[0] || {}).map(k => <th key={k}>{k}</th>)}
                                                    </tr>
                                                </thead>
                                                <tbody>
                                                    {executionResult.data.slice(0, 5).map((row, i) => (
                                                        <tr key={i}>
                                                            {Object.values(row).map((val, j) => <td key={j}>{JSON.stringify(val)}</td>)}
                                                        </tr>
                                                    ))}
                                                </tbody>
                                            </table>
                                            {executionResult.data.length > 5 && <p className="more-rows">... {executionResult.data.length - 5} more rows</p>}
                                        </div>
                                    ) : (
                                        <pre>{JSON.stringify(executionResult.data, null, 2)}</pre>
                                    )}
                                </div>
                            )}
                        </div>
                    ) : (
                        <div className="error-output">
                            <pre className="console-output">{executionResult.stderr}</pre>
                        </div>
                    )}
                </div>
            )}
        </div>
    )
}

export default AnalysisView
