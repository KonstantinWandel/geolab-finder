function ResultsList({ results, onSelect }) {
    if (!results.length) return null

    return (
        <div className="results-grid">
            {results.map((item) => (
                <div
                    key={item.code}
                    className="result-card glass-panel"
                    onClick={() => onSelect(item)}
                >
                    <div className="card-header">
                        <span className="badge-code">{item.code}</span>
                        <span className="badge-score">Relevance: {((1 - item.score / 2) * 100).toFixed(0)}%</span>
                    </div>
                    <h3>{item.title}</h3>
                    <p className="card-hint">Click to analyze this table</p>
                </div>
            ))}
        </div>
    )
}

export default ResultsList
