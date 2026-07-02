import { useState, useEffect } from 'react'
import SearchBar from './components/SearchBar'
import ResultsList from './components/ResultsList'
import AnalysisView from './components/AnalysisView'
import SOEPView from './components/SOEPView'
import SOEPRagAdvisor from './components/SOEPRagAdvisor'
import './App.css'

function App() {
  const [results, setResults] = useState([])
  const [selectedTable, setSelectedTable] = useState(null)
  const [loading, setLoading] = useState(false)
  const [activeView, setActiveView] = useState('search') // 'search', 'soep', 'advisor'

  const API_URL = import.meta.env.VITE_API_URL || "/api"
  const APP_MODE = import.meta.env.VITE_APP_MODE || "all"

  const [theme, setTheme] = useState(() => {
    const allowed = ['default', 'dark', 'light']
    try {
      const t = localStorage.getItem('geolab_theme')
      return allowed.includes(t) ? t : 'default'
    } catch (e) {
      return 'default'
    }
  })
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    try { localStorage.setItem('geolab_theme', theme) } catch (e) { /* ignore */ }
  }, [theme])
  const TITLES = {
    soep: "SOEP Variable Finder",
    inkar: "INKAR Regional Indicators",
    all: "Data Platform",
  }

  const handleSearch = async (query) => {
    setLoading(true)
    setSelectedTable(null)
    try {
      const res = await fetch(`${API_URL}/search`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query, k: 5 })
      })
      const data = await res.json()
      setResults(data)
    } catch (err) {
      console.error(err)
    } finally {
      setLoading(false)
    }
  }

  const handleSelectTable = (table) => {
    setSelectedTable(table)
  }

  return (
    <div className="app-container">
      <header className="app-header">
        <h1>GeoLAB <span className="text-gradient">{TITLES[APP_MODE] || TITLES.all}</span></h1>
        <select className="theme-select" value={theme} onChange={(e) => setTheme(e.target.value)} aria-label="Theme">
          <option value="default">Default</option>
          <option value="dark">Dark</option>
          <option value="light">Light</option>
        </select>
      </header>
      <main className="main-content">
        <SOEPRagAdvisor apiUrl={API_URL} mode={APP_MODE} />
      </main>
    </div>
  )
}

export default App
