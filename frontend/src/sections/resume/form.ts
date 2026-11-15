import type { MasterResume } from '../../api.ts'

// Form-side shapes: achievements and skills are edited as text (one per line),
// and every repeated row has a stable key so reordering keeps the right inputs.
export interface RoleRow {
  key: number
  employer: string
  title: string
  start: string
  end: string
  location: string
  bullets: string
}
export interface EduRow {
  key: number
  school: string
  degree: string
  field: string
  year: string
}
export interface CertRow {
  key: number
  name: string
  issuer: string
  year: string
}
export interface ResumeForm {
  summary: string
  roles: RoleRow[]
  skills: string
  education: EduRow[]
  certifications: CertRow[]
}

let nextKey = 1
export const newKey = () => nextKey++

export const blankRole = (): RoleRow => ({ key: newKey(), employer: '', title: '', start: '', end: '', location: '', bullets: '' })
export const blankEdu = (): EduRow => ({ key: newKey(), school: '', degree: '', field: '', year: '' })
export const blankCert = (): CertRow => ({ key: newKey(), name: '', issuer: '', year: '' })

export function toForm(r: MasterResume): ResumeForm {
  return {
    summary: r.summary,
    roles: r.roles.map((x) => ({ ...x, key: newKey(), bullets: x.bullets.join('\n') })),
    skills: r.skills.join('\n'),
    education: r.education.map((x) => ({ ...x, key: newKey() })),
    certifications: r.certifications.map((x) => ({ ...x, key: newKey() })),
  }
}

export const emptyResume = (): MasterResume => ({ summary: '', roles: [], skills: [], education: [], certifications: [] })

export const lines = (t: string) =>
  t
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean)
const blank = (...v: string[]) => v.every((s) => !s.trim())

// Throws a plain-language Error when a row is half filled in. Rows left completely empty are dropped.
export function fromForm(f: ResumeForm): MasterResume {
  const roles = f.roles.filter((r) => !blank(r.employer, r.title, r.start, r.end, r.location, r.bullets))
  if (roles.some((r) => !r.employer.trim() || !r.title.trim()))
    throw new Error('Each job needs an employer and a job title.')
  const education = f.education.filter((e) => !blank(e.school, e.degree, e.field, e.year))
  if (education.some((e) => !e.school.trim())) throw new Error('Each education entry needs a school.')
  const certifications = f.certifications.filter((c) => !blank(c.name, c.issuer, c.year))
  if (certifications.some((c) => !c.name.trim())) throw new Error('Each certification needs a name.')
  return {
    summary: f.summary.trim(),
    roles: roles.map((r) => ({
      employer: r.employer.trim(),
      title: r.title.trim(),
      start: r.start.trim(),
      end: r.end.trim(),
      location: r.location.trim(),
      bullets: lines(r.bullets),
    })),
    skills: lines(f.skills),
    education: education.map((e) => ({
      school: e.school.trim(),
      degree: e.degree.trim(),
      field: e.field.trim(),
      year: e.year.trim(),
    })),
    certifications: certifications.map((c) => ({ name: c.name.trim(), issuer: c.issuer.trim(), year: c.year.trim() })),
  }
}
