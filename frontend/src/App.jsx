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
      // Light is the default: the finders are read in bright seminar rooms and printed from,
      // and the dark theme is an explicit opt-in that persists per browser.
      return allowed.includes(t) ? t : 'light'
    } catch (e) {
      return 'light'
    }
  })
  useEffect(() => {
    // index.html carries %VITE_PAGE_TITLE%, substituted at build time per mode. This keeps
    // the tab correct even when a build forgets to pass it.
    const pageTitle = TITLES[APP_MODE] ? `${TITLES[APP_MODE]}` : 'GeoLAB metadata finder'
    if (!document.title || document.title.startsWith('%')) document.title = pageTitle
  }, [APP_MODE])

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    try { localStorage.setItem('geolab_theme', theme) } catch (e) { /* ignore */ }
  }, [theme])
  // Institutional marks per deployment. Files live in public/brand/ and are served from the
  // site itself; the SVGs use fill: currentColor so they work in the dark theme too.
  // Monochrome marks are drawn as CSS masks filled with currentColor: an <img> renders the
  // SVG in its own document, where fill: currentColor resolves to black, so the marks
  // disappeared on the dark themes. The SOEP mark is a multi-colour raster, so it stays an
  // <img> and gets a light plate behind it on dark backgrounds instead.
  const UNI = { file: 'uni-bielefeld.svg', alt: 'Universität Bielefeld', kind: 'mask',
                url: 'https://www.uni-bielefeld.de/', shape: 'brand-uni' }
  const LEIBNIZ = { file: 'leibniz.svg', alt: 'Leibniz-Gemeinschaft', kind: 'mask',
                    url: 'https://www.leibniz-gemeinschaft.de/', shape: 'brand-leibniz' }
  const DIW = { file: 'diw.svg', alt: 'DIW Berlin', kind: 'mask',
                url: 'https://www.diw.de/', shape: 'brand-diw' }
  const SOEP = { file: 'soep.png', alt: 'Sozio-oekonomisches Panel (SOEP)', kind: 'img',
                 url: 'https://www.diw.de/soep', shape: 'brand-soep' }
  // Both finders are the same project, so both carry the same four marks.
  const BRAND_SETS = {
    soep: [UNI, DIW, SOEP, LEIBNIZ],
    inkar: [UNI, DIW, SOEP, LEIBNIZ],
    all: [UNI, DIW, SOEP, LEIBNIZ],
  }
  const BRANDS = BRAND_SETS[APP_MODE] || BRAND_SETS.all

  const TITLES = {
    soep: "SOEP Variable Finder",
    inkar: "GeoDB Geodata Index",
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
      <footer className="brand-strip">
        {BRANDS.map((brand) => (
          <a key={brand.file} href={brand.url} target="_blank" rel="noopener noreferrer" aria-label={brand.alt}>
            {brand.kind === 'mask' ? (
              <span role="img" aria-label={brand.alt} title={brand.alt}
                    className={`brand-logo brand-mark ${brand.shape}`} />
            ) : (
              <img
                src={`/brand/${brand.file}`}
                alt={brand.alt}
                className={`brand-logo ${brand.shape}`}
                /* A logo file that is not present yet should leave no broken-image icon. */
                onError={(e) => { e.currentTarget.parentElement.style.display = 'none' }}
              />
            )}
          </a>
        ))}
      </footer>
    </div>
  )
}

export default App
