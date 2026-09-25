import { Component, useState, useEffect } from 'react'
import SearchBar from './components/SearchBar'
import ResultsList from './components/ResultsList'
import AnalysisView from './components/AnalysisView'
import SOEPView from './components/SOEPView'
import SOEPRagAdvisor from './components/SOEPRagAdvisor'
import { LANGUAGES, detectLanguage, makeTranslator } from './i18n'
import './App.css'
import './geolab-fonts.css'

const TAG = 24 * 60 * 60 * 1000

/* Eine weiße Seite ist die schlechteste Fehlermeldung, die es gibt: der Besucher sieht nichts,
   der Betreiber erfährt nichts, und der Rat "Cache leeren" hilft nicht, weil der Verlauf im
   localStorage liegt und nicht im Cache. Stirbt der Aufbau, steht hier ab jetzt, was los ist,
   mit einem Knopf, der den gespeicherten Verlauf wegräumt und neu lädt. */
class Absturzfang extends Component {
  constructor(props) {
    super(props)
    this.state = { fehler: null }
  }
  static getDerivedStateFromError(fehler) {
    return { fehler }
  }
  componentDidCatch(fehler, info) {
    console.error('Aufbau abgebrochen:', fehler, info)
  }
  render() {
    if (!this.state.fehler) return this.props.children
    return (
      <div className="glass-panel" style={{ padding: '1.5rem', margin: '2rem auto', maxWidth: '46rem' }}>
        <h2 style={{ marginTop: 0 }}>{this.props.t('crash.title')}</h2>
        <p>{this.props.t('crash.body')}</p>
        <p style={{ fontFamily: 'var(--mono, monospace)', fontSize: '0.85rem', opacity: 0.75 }}>
          {String(this.state.fehler && this.state.fehler.message || this.state.fehler).slice(0, 200)}
        </p>
        <button
          type="button"
          className="btn-primary"
          onClick={() => {
            try {
              Object.keys(localStorage)
                .filter((k) => k.startsWith('geolab_history_'))
                .forEach((k) => localStorage.removeItem(k))
            } catch (e) { /* gesperrter Speicher: dann eben nur neu laden */ }
            window.location.reload()
          }}
        >
          {this.props.t('crash.reset')}
        </button>
      </div>
    )
  }
}

function App() {
  const [results, setResults] = useState([])
  const [selectedTable, setSelectedTable] = useState(null)
  const [loading, setLoading] = useState(false)
  const [activeView, setActiveView] = useState('search') // 'search', 'soep', 'advisor'

  const API_URL = import.meta.env.VITE_API_URL || "/api"
  const APP_MODE = import.meta.env.VITE_APP_MODE || "all"

  // Darstellung. Voreinstellung ist das System; wer von Hand umschaltet, bekommt seine Wahl
  // 24 Stunden lang und danach wieder die Systemeinstellung. Dieselbe Regel gilt auf der
  // GeoLAB-Seite, damit ein einmaliges Umschalten nicht zur Dauereinstellung wird.
  // Die Auswertung vor dem ersten Zeichnen steht gleichlautend in index.html.
  const [theme, setTheme] = useState(() => {
    try {
      const roh = localStorage.getItem('geolab_theme')
      if (!roh || roh[0] !== '{') return 'system'   // ältere Builds legten den nackten Namen ab
      const { wert, zeit } = JSON.parse(roh)
      if (wert !== 'dark' && wert !== 'light') return 'system'
      // Ein Zeitstempel aus der Zukunft kommt von einer zurückgestellten Uhr und gilt als abgelaufen.
      if (typeof zeit !== 'number' || zeit > Date.now() || Date.now() - zeit >= TAG) return 'system'
      return wert
    } catch (e) {
      return 'system'
    }
  })
  const [systemDunkel, setSystemDunkel] = useState(() => {
    try { return window.matchMedia('(prefers-color-scheme: dark)').matches } catch (e) { return false }
  })
  useEffect(() => {
    let mq
    try { mq = window.matchMedia('(prefers-color-scheme: dark)') } catch (e) { return undefined }
    const beiWechsel = (e) => setSystemDunkel(e.matches)
    mq.addEventListener('change', beiWechsel)
    return () => mq.removeEventListener('change', beiWechsel)
  }, [])
  const wirksamesThema = theme === 'system' ? (systemDunkel ? 'dark' : 'light') : theme

  // Der Zeitstempel wird nur bei einer Wahl geschrieben, nicht bei jedem Aufruf: sonst würde
  // jeder Besuch die 24 Stunden neu starten und die Wahl liefe nie ab.
  const chooseTheme = (value) => {
    setTheme(value)
    try {
      if (value === 'system') localStorage.removeItem('geolab_theme')
      else localStorage.setItem('geolab_theme', JSON.stringify({ wert: value, zeit: Date.now() }))
    } catch (e) { /* ignore */ }
  }
  useEffect(() => {
    // index.html carries %VITE_PAGE_TITLE%, substituted at build time per mode. This keeps
    // the tab correct even when a build forgets to pass it.
    const pageTitle = TITLES[APP_MODE] ? `${TITLES[APP_MODE]}` : 'GeoLAB metadata finder'
    if (!document.title || document.title.startsWith('%')) document.title = pageTitle
  }, [APP_MODE])

  // English is the default; a choice the user makes persists per browser.
  const [language, setLanguage] = useState(detectLanguage)
  const t = makeTranslator(language)
  useEffect(() => {
    document.documentElement.setAttribute('lang', language)
  }, [language])

  // Written only when the user picks a language, never for the detected default. Storing the
  // default too would have kept every returning German-browser visitor on German forever, since
  // the stored value wins over the new default.
  const chooseLanguage = (value) => {
    setLanguage(value)
    try { localStorage.setItem('geolab_lang', value) } catch (e) { /* ignore */ }
  }

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', wirksamesThema)
  }, [wirksamesThema])
  // Institutional marks per deployment. Files live in public/brand/ and are served from the
  // site itself; the SVGs use fill: currentColor so they work in the dark theme too.
  // Monochrome marks are drawn as CSS masks filled with currentColor: an <img> renders the
  // SVG in its own document, where fill: currentColor resolves to black, so the marks
  // disappeared on the dark themes. The SOEP mark is a multi-colour raster, so it stays an
  // <img> and gets a light plate behind it on dark backgrounds instead.
  // The same four marks in the same order as the project site's footer, including the combined
  // DIW-SOEP mark that replaced the two single ones there on 2026-09-09.
  const REGIOHUB = { file: 'regiohub.png', alt: 'Leibniz ScienceCampus SOEP RegioHub', kind: 'img',
                     url: 'https://lsc-soep-regiohub.com/', shape: 'brand-regiohub' }
  const UNI = { file: 'uni-bielefeld.svg', alt: 'Universität Bielefeld', kind: 'mask',
                url: 'https://www.uni-bielefeld.de/', shape: 'brand-uni' }
  const DIWSOEP = { file: 'diw-soep.png', alt: 'DIW Berlin und das Sozio-oekonomische Panel (SOEP)',
                    kind: 'img', url: 'https://www.diw.de/en/soep', shape: 'brand-diwsoep' }
  const LEIBNIZ = { file: 'leibniz.svg', alt: 'Leibniz-Gemeinschaft', kind: 'mask',
                    url: 'https://www.leibniz-gemeinschaft.de/', shape: 'brand-leibniz' }
  // Both finders are the same project, so both carry the same four marks.
  const BRAND_SETS = {
    soep: [REGIOHUB, UNI, DIWSOEP, LEIBNIZ],
    inkar: [REGIOHUB, UNI, DIWSOEP, LEIBNIZ],
    all: [REGIOHUB, UNI, DIWSOEP, LEIBNIZ],
  }
  const BRANDS = BRAND_SETS[APP_MODE] || BRAND_SETS.all
  // The project site. It used to be addressed by its old GitLab Pages URL, which only still works
  // because a redirect was left behind there.
  const GEOLAB_SITE = 'https://geolab.soz.uni-bielefeld.de'

  const TITLES = {
    soep: "SOEP Variable Finder",
    inkar: "GeoDB",
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

  const controls = (
    <div className="header-controls">
      <select className="theme-select" value={language} onChange={(e) => chooseLanguage(e.target.value)} aria-label={t('lang.aria')}>
        {LANGUAGES.map((entry) => (
          <option key={entry.value} value={entry.value}>{entry.label}</option>
        ))}
      </select>
      <select className="theme-select" value={theme} onChange={(e) => chooseTheme(e.target.value)} aria-label={t('theme.aria')}>
        <option value="system">{t('theme.system')}</option>
        <option value="dark">{t('theme.dark')}</option>
        <option value="light">{t('theme.light')}</option>
      </select>
    </div>
  )

  return (
    <div className="app-container">
      {APP_MODE === 'inkar' || APP_MODE === 'soep' ? (
        /* Both finders wear the GeoLAB site's header: the mark and wordmark lead back to the site,
           its menu follows, and the finder stands at the end as the page you are on. Benchmarking is left
           out on purpose: that page is unfinished and gets no new links until it is ready. */
        <header className="app-header gl-header">
          <a className="gl-brand" href={`${GEOLAB_SITE}/`}>
            <img className="gl-mark gl-mark-light" src="/brand/geolab-mark.svg" alt="" />
            <img className="gl-mark gl-mark-dark" src="/brand/geolab-mark-invert.svg" alt="" />
            <span>GeoLAB</span>
          </a>
          <nav className="gl-nav" aria-label="GeoLAB">
            <a href={`${GEOLAB_SITE}/Linking.html`}>Linking</a>
            <a href={`${GEOLAB_SITE}/Accessing.html`}>Accessing</a>
            <a href={`${GEOLAB_SITE}/about.html`}>About</a>
            <a href={`${GEOLAB_SITE}/why.html`}>Why Geodata?</a>
            {/* GeoDB is the tool most visitors come for, so it is one click away from either
                finder; on GeoDB itself it is the page you are on. */}
            {APP_MODE === 'inkar'
              ? <span className="gl-current" aria-current="page"><h1>{TITLES.inkar}</h1></span>
              : <a href="https://geodb.geolab.soz.uni-bielefeld.de/">{TITLES.inkar}</a>}
            {APP_MODE === 'soep' && (
              <span className="gl-current" aria-current="page"><h1>{TITLES.soep}</h1></span>
            )}
          </nav>
          {controls}
        </header>
      ) : (
        <header className="app-header">
          <h1>GeoLAB <span className="text-gradient">{TITLES[APP_MODE] || TITLES.all}</span></h1>
          {controls}
        </header>
      )}
      <main className="main-content">
        <Absturzfang t={t}>
          <SOEPRagAdvisor apiUrl={API_URL} mode={APP_MODE} language={language} />
        </Absturzfang>
      </main>
      {/* The same footer as the project site: a row of partner marks under a label, then three
          columns for what this is, how to reach us, and the legal pages. The finders add their
          own citation line, which the site has no need for. */}
      <footer className="site-footer">
        <div className="footer-partners">
          <p className="footer-label">{t('footer.partners')}</p>
          <div className="brand-strip">
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
          </div>
        </div>
        <div className="footer-cols">
          <div>
            <img className="footer-mark" src="/brand/geolab-mark.svg" alt="" />
            <strong className="footer-brand-name">GeoLAB</strong>
            <p>{t('footer.blurb')}</p>
          </div>
          <div>
            <strong>{t('footer.contact')}</strong>
            <p><a href="mailto:geolab@uni-bielefeld.de">geolab@uni-bielefeld.de</a></p>
          </div>
          <div>
            <strong>{t('footer.legal')}</strong>
            <p>
              <a href={`${GEOLAB_SITE}/imprint.html`} target="_blank" rel="noreferrer">{t('legal.imprint')}</a><br />
              <a href={`${GEOLAB_SITE}/privacy.html`} target="_blank" rel="noreferrer">{t('legal.privacy')}</a><br />
              <a href={`${GEOLAB_SITE}/data-sources.html`} target="_blank" rel="noreferrer">{t('legal.sources')}</a><br />
              <a href={GEOLAB_SITE} target="_blank" rel="noreferrer">GeoLAB</a>
            </p>
          </div>
        </div>
      </footer>
    </div>
  )
}

export default App
