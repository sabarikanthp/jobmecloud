import type { MasterResume, ResumeMapping } from '../../api.ts'
import Tip from '../../components/Tip.tsx'

const TIP =
  'JobMe only rewrites paragraphs labelled Summary, Skills or a bullet. Everything labelled Keep as is stays exactly as you wrote it. Headline is the line under your name; JobMe may tailor it to each job. Title lines (job title, company, dates) always stay exactly as you wrote them.'

const cut = (t: string) => (t.length > 120 ? `${t.slice(0, 120)}…` : t)

export default function MappingReview({
  mapping,
  reading,
  onChange,
}: {
  mapping: ResumeMapping
  reading: MasterResume
  onChange: (m: ResumeMapping) => void
}) {
  const bullets = reading.roles.flatMap((role, i) =>
    role.bullets.map((_, j) => ({
      value: `bullet:${i}:${j}`,
      label: `${role.title} at ${role.employer}: bullet ${j + 1}`,
    })),
  )
  const known = new Set(['contact', 'headline', 'summary', 'title', 'skills', 'keep', ...bullets.map((b) => b.value)])

  function setLabel(index: number, label: string) {
    // Keep role_keys and stale: the server uses them to follow jobs that were moved.
    onChange({ ...mapping, paragraphs: mapping.paragraphs.map((p) => (p.index === index ? { ...p, label } : p)) })
  }

  return (
    <div className="mapping-review">
      <h4>
        Check the layout
        <Tip text={TIP} />
      </h4>
      {mapping.stale && (
        <p className="help">The jobs in this resume changed after the mapping was made. Check each paragraph, then Save.</p>
      )}
      {mapping.paragraphs
        .filter((p) => p.text.trim())
        .map((p) => (
          <div className="row" key={p.index}>
            <span>{cut(p.text)}</span>
            <select
              aria-label={`What is "${cut(p.text)}"?`}
              value={p.label}
              onChange={(e) => setLabel(p.index, e.target.value)}
            >
              <option value="contact">Contact</option>
              <option value="headline">Headline</option>
              <option value="summary">Summary</option>
              <option value="title">Title</option>
              <option value="skills">Skills</option>
              <option value="keep">Keep as is</option>
              {bullets.map((b) => (
                <option key={b.value} value={b.value}>
                  {b.label}
                </option>
              ))}
              {!known.has(p.label) && <option value={p.label}>{p.label}</option>}
            </select>
          </div>
        ))}
    </div>
  )
}
