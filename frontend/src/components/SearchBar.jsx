import { useState } from 'react'

function SearchBar({ onSearch, loading }) {
    const [query, setQuery] = useState('')

    const handleSubmit = (e) => {
        e.preventDefault()
        if (query.trim()) onSearch(query)
    }

    return (
        <div className="search-container">
            <form onSubmit={handleSubmit} className="search-form glass-panel">
                <input
                    type="text"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder="Ask a question about German statistics (e.g., 'Arbeitslosigkeit Berlin 2019')"
                    className="search-input"
                    disabled={loading}
                />
                <button type="submit" className="btn-primary" disabled={loading}>
                    {loading ? 'Thinking...' : 'Search'}
                </button>
            </form>
        </div>
    )
}

export default SearchBar
