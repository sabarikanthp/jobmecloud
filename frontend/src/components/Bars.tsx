export interface BarItem {
  label: string
  value: number
  caption?: string
}

export function Bars({
  items,
  max,
  unit = '',
  colour = 'var(--accent)',
}: {
  items: BarItem[]
  max?: number
  unit?: string
  colour?: string
}) {
  const top = Math.max(max ?? 0, ...items.map((i) => i.value), 1)
  return (
    <div className="bars" role="list">
      {items.map((i) => (
        <div className="bar-row" role="listitem" key={i.label}>
          <span className="bar-label">{i.label}</span>
          <span className="bar-track" aria-hidden="true">
            <span className="bar-fill" style={{ width: `${Math.min(100, (i.value / top) * 100)}%`, background: colour }} />
          </span>
          <span className="bar-value">
            {i.value}
            {unit}
            {i.caption && <span className="bar-caption"> {i.caption}</span>}
          </span>
        </div>
      ))}
    </div>
  )
}

const STEP = 40
const BAR = 28
const HEIGHT = 140
const BASE = 120

export function Columns({
  items,
  colour = 'var(--accent)',
  noun = 'applications',
}: {
  items: { label: string; value: number }[]
  colour?: string
  noun?: string
}) {
  const top = Math.max(...items.map((i) => i.value), 1)
  const width = items.length * STEP
  return (
    <div className="columns">
      <svg viewBox={`0 0 ${width} ${HEIGHT}`} width={width} height={HEIGHT} role="img" aria-label={`${noun} per week`}>
        <line x1="0" x2={width} y1={BASE} y2={BASE} stroke="var(--border)" />
        {items.map((i, n) => {
          const h = (i.value / top) * (BASE - 20)
          const x = n * STEP + (STEP - BAR) / 2
          return (
            <g key={`${i.label}-${n}`}>
              <rect x={x} y={BASE - h} width={BAR} height={h} fill={colour}>
                <title>{`Week of ${i.label}: ${i.value} ${noun}`}</title>
              </rect>
              {i.value > 0 && (
                <text x={x + BAR / 2} y={BASE - h - 4} textAnchor="middle" fontSize="11" fill="var(--text)">
                  {i.value}
                </text>
              )}
              {n % 2 === 0 && (
                <text x={x + BAR / 2} y={BASE + 14} textAnchor="middle" fontSize="9" fill="var(--muted)">
                  {i.label}
                </text>
              )}
            </g>
          )
        })}
      </svg>
    </div>
  )
}
