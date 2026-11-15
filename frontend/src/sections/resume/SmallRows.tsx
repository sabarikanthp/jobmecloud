import type { CertRow, EduRow } from './form.ts'

interface RowProps<T> {
  row: T
  onChange: (r: T) => void
  onRemove: () => void
}

export function EducationEditor({ row, onChange, onRemove }: RowProps<EduRow>) {
  const set = (k: keyof EduRow) => (e: { target: { value: string } }) => onChange({ ...row, [k]: e.target.value })
  return (
    <div className="card">
      <label>
        School
        <input value={row.school} onChange={set('school')} />
        <span className="help">The college or school.</span>
      </label>
      <label>
        Degree
        <input value={row.degree} onChange={set('degree')} />
        <span className="help">For example, BS.</span>
      </label>
      <label>
        Field
        <input value={row.field} onChange={set('field')} />
        <span className="help">What you studied.</span>
      </label>
      <label>
        Year
        <input value={row.year} onChange={set('year')} />
        <span className="help">The year you finished.</span>
      </label>
      <div className="row">
        <button className="danger" onClick={onRemove}>Remove</button>
      </div>
    </div>
  )
}

export function CertificationEditor({ row, onChange, onRemove }: RowProps<CertRow>) {
  const set = (k: keyof CertRow) => (e: { target: { value: string } }) => onChange({ ...row, [k]: e.target.value })
  return (
    <div className="card">
      <label>
        Name
        <input value={row.name} onChange={set('name')} />
        <span className="help">The name of the certification.</span>
      </label>
      <label>
        Issuer
        <input value={row.issuer} onChange={set('issuer')} />
        <span className="help">Who awarded it.</span>
      </label>
      <label>
        Year
        <input value={row.year} onChange={set('year')} />
        <span className="help">The year you earned it.</span>
      </label>
      <div className="row">
        <button className="danger" onClick={onRemove}>Remove</button>
      </div>
    </div>
  )
}
