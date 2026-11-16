import type { FitResult } from '../api.ts'

// How well a job fits: the score beside the cutoff, why, what is missing, and anything worth a second look.
export default function FitCard({ fit }: { fit: FitResult }) {
  const failed = fit.rules.filter((r) => !r.passed)
  return (
    <div className="fit-card">
      <p className="fit-score">
        <strong className={fit.above_cutoff ? 'fit-good' : 'fit-low'}>{fit.score}</strong>
        <span className="muted"> out of 100 (cutoff {fit.cutoff})</span>
      </p>
      {fit.reasons && (
        <>
          <h4>Why it fits</h4>
          <p>{fit.reasons}</p>
        </>
      )}
      {fit.gaps && (
        <>
          <h4>Gaps</h4>
          <p>{fit.gaps}</p>
        </>
      )}
      {fit.warnings.length > 0 && (
        <>
          <h4>Worth a look</h4>
          <ul>
            {fit.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </>
      )}
      {failed.length > 0 && (
        <>
          <h4>Rules this job breaks</h4>
          <ul>
            {failed.map((r) => (
              <li key={r.rule}>
                <strong>{r.rule}</strong>
                {r.note ? `: ${r.note}` : ''}
              </li>
            ))}
          </ul>
        </>
      )}
      <p className="help">
        Judged by {fit.model}, about ${fit.cost_usd.toFixed(2)}.
      </p>
    </div>
  )
}
