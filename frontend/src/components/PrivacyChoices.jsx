import { useEffect, useState } from 'react'

export default function PrivacyChoices({ consent, onSave, t, notice }) {
  const [history, setHistory] = useState(consent.history)
  const [analytics, setAnalytics] = useState(consent.analytics)
  useEffect(() => { setHistory(consent.history); setAnalytics(consent.analytics) }, [consent])
  return (
    <section className="privacy-choices" id="privacy-settings" aria-labelledby="privacy-heading" tabIndex={-1}>
      <div className="privacy-inner">
        <h2 id="privacy-heading">{t('privacy.title')}</h2>
        <p>{t('privacy.body')} <a href="https://geolab.soz.uni-bielefeld.de/privacy.html" target="_blank" rel="noreferrer">{t('legal.privacy')}</a></p>
        <div className="privacy-options">
          <label><input type="checkbox" checked={history} onChange={(e) => setHistory(e.target.checked)} />
            <span><strong>{t('privacy.history')}</strong><small>{t('privacy.historyDetail')}</small></span></label>
          <label><input type="checkbox" checked={analytics} onChange={(e) => setAnalytics(e.target.checked)} />
            <span><strong>{t('privacy.analytics')}</strong><small>{t('privacy.analyticsDetail')}</small></span></label>
        </div>
        <div className="privacy-actions">
          <button type="button" className="btn-secondary" onClick={() => onSave({ history: false, analytics: false })}>{t('privacy.decline')}</button>
          <button type="button" className="btn-secondary" onClick={() => onSave({ history: true, analytics: true })}>{t('privacy.allow')}</button>
          <button type="button" className="btn-secondary" onClick={() => onSave({ history, analytics })}>{t('privacy.save')}</button>
        </div>
        {notice && <p role="status">{notice}</p>}
      </div>
    </section>
  )
}
