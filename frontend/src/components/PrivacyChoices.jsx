import { useEffect, useLayoutEffect, useRef, useState } from 'react'

export default function PrivacyChoices({ consent, onSave, t, notice }) {
  const [history, setHistory] = useState(consent.history)
  const [analytics, setAnalytics] = useState(consent.analytics)
  const [quality, setQuality] = useState(consent.quality)
  const ref = useRef(null)
  useEffect(() => { setHistory(consent.history); setAnalytics(consent.analytics); setQuality(consent.quality) }, [consent])
  useLayoutEffect(() => {
    const size = () => document.documentElement.style.setProperty('--privacy-height', `${ref.current?.getBoundingClientRect().height || 0}px`)
    size()
    const observer = new ResizeObserver(size)
    observer.observe(ref.current)
    return () => { observer.disconnect(); document.documentElement.style.removeProperty('--privacy-height') }
  }, [])
  return (
    <section ref={ref} className="privacy-choices" id="privacy-settings" aria-labelledby="privacy-heading" tabIndex={-1}>
      <div className="privacy-inner">
        <h2 id="privacy-heading">{t('privacy.title')}</h2>
        <p>{t('privacy.body')} <a href="https://geolab.soz.uni-bielefeld.de/privacy.html" target="_blank" rel="noreferrer">{t('legal.privacy')}</a></p>
        <details className="privacy-customize">
          <summary>{t('privacy.customize')}</summary>
          <div className="privacy-options">
          <label><input type="checkbox" checked={history} onChange={(e) => setHistory(e.target.checked)} />
            <span><strong>{t('privacy.history')}</strong><small>{t('privacy.historyDetail')}</small></span></label>
          <label><input type="checkbox" checked={analytics} onChange={(e) => setAnalytics(e.target.checked)} />
            <span><strong>{t('privacy.analytics')}</strong><small>{t('privacy.analyticsDetail')}</small></span></label>
          <label><input type="checkbox" checked={quality} onChange={(e) => setQuality(e.target.checked)} />
            <span><strong>{t('privacy.quality')}</strong><small>{t('privacy.qualityDetail')}</small></span></label>
          </div>
          <button type="button" className="btn-secondary" onClick={() => onSave({ history, analytics, quality })}>{t('privacy.save')}</button>
        </details>
        <div className="privacy-actions">
          <button type="button" className="btn-secondary" onClick={() => onSave({ history: false, analytics: false, quality: false })}>{t('privacy.decline')}</button>
          <button type="button" className="btn-secondary" onClick={() => onSave({ history: true, analytics: true, quality: true })}>{t('privacy.allow')}</button>
        </div>
        {notice && <p role="status">{notice}</p>}
      </div>
    </section>
  )
}
