import { useState } from 'react'
import { ThumbsUp, ThumbsDown } from 'lucide-react'

export default function ResultFeedback({ apiUrl, result, row, t }) {
  const [vote, setVote] = useState(null)
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState(false)
  const icons = { useful: <ThumbsUp size={16} aria-hidden="true" />,
    not_useful: <ThumbsDown size={16} aria-hidden="true" /> }
  if (!result.query_id || !result.feedback_token || !row.item_id) return null
  const send = async (value) => {
    setBusy(true)
    setFailed(false)
    try {
      const response = await fetch(`${apiUrl}/soep/feedback`, { method: 'POST',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
          query_id: result.query_id, item_id: row.item_id, vote: value, token: result.feedback_token }) })
      if (!response.ok) throw new Error('Feedback unavailable')
      setVote(value)
    } catch { setFailed(true) } finally { setBusy(false) }
  }
  return (
    <div className="result-feedback" role="group" aria-label={t('feedback.label')}>
      {['useful', 'not_useful'].map((value) => (
        <button key={value} type="button" disabled={busy} aria-pressed={vote === value}
          title={t(`feedback.${value}`)} aria-label={t(`feedback.${value}`)} onClick={() => send(value)}>
          {icons[value]}
        </button>
      ))}
      <span role="status">{failed ? t('feedback.failed') : vote ? t('feedback.saved') : ''}</span>
    </div>
  )
}
