import { useEffect, useRef, useState } from 'react'
import {
  draftResume,
  getMapping,
  getResume,
  getResumeReading,
  listResumes,
  makeDefault,
  removeResume,
  saveMapping,
  saveNewResume,
  saveResume,
  type MasterResume,
  type ResumeDraft,
  type ResumeList,
  type ResumeMapping,
} from '../api.ts'
import SectionCard, { type SectionMode } from '../components/SectionCard.tsx'
import MappingReview from './resume/MappingReview.tsx'
import AddResumeFolder from './resume/AddResumeFolder.tsx'
import RoleEditor from './resume/RoleEditor.tsx'
import { CertificationEditor, EducationEditor } from './resume/SmallRows.tsx'
import { blankCert, blankEdu, blankRole, fromForm, toForm, type ResumeForm } from './resume/form.ts'

const ACCEPT = '.docx,.pdf,.txt,.md'

function move<T>(list: T[], i: number, delta: number): T[] {
  const j = i + delta
  if (j < 0 || j >= list.length) return list
  const out = [...list]
  ;[out[i], out[j]] = [out[j], out[i]]
  return out
}
const replaceAt = <T,>(list: T[], i: number, v: T) => list.map((x, n) => (n === i ? v : x))
const removeAt = <T,>(list: T[], i: number) => list.filter((_, n) => n !== i)
const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`
const errText = (e: unknown) => (e instanceof Error ? e.message : 'Something went wrong.')

function ReadingForm({ form, update }: { form: ResumeForm; update: (patch: Partial<ResumeForm>) => void }) {
  return (
    <>
      <label>
        Summary
        <textarea rows={4} value={form.summary} onChange={(e) => update({ summary: e.target.value })} />
        <span className="help">A few sentences about you and what you do best.</span>
      </label>
      <h4>Jobs</h4>
      {form.roles.map((r, i) => (
        <RoleEditor
          key={r.key}
          role={r}
          index={i}
          count={form.roles.length}
          onChange={(v) => update({ roles: replaceAt(form.roles, i, v) })}
          onMove={(d) => update({ roles: move(form.roles, i, d) })}
          onRemove={() => update({ roles: removeAt(form.roles, i) })}
        />
      ))}
      <div className="row">
        <button className="add" onClick={() => update({ roles: [...form.roles, blankRole()] })}>Add a job</button>
      </div>
      <label>
        Skills (one per line)
        <textarea rows={6} value={form.skills} onChange={(e) => update({ skills: e.target.value })} />
        <span className="help">Tools, methods and strengths you want employers to see.</span>
      </label>
      <h4>Education</h4>
      {form.education.map((r, i) => (
        <EducationEditor
          key={r.key}
          row={r}
          onChange={(v) => update({ education: replaceAt(form.education, i, v) })}
          onRemove={() => update({ education: removeAt(form.education, i) })}
        />
      ))}
      <div className="row">
        <button className="add" onClick={() => update({ education: [...form.education, blankEdu()] })}>Add education</button>
      </div>
      <h4>Certifications</h4>
      {form.certifications.map((r, i) => (
        <CertificationEditor
          key={r.key}
          row={r}
          onChange={(v) => update({ certifications: replaceAt(form.certifications, i, v) })}
          onRemove={() => update({ certifications: removeAt(form.certifications, i) })}
        />
      ))}
      <div className="row">
        <button className="add" onClick={() => update({ certifications: [...form.certifications, blankCert()] })}>
          Add a certification
        </button>
      </div>
    </>
  )
}

type View =
  | { kind: 'list' }
  | { kind: 'upload'; draft: ResumeDraft; name: string; form: ResumeForm; mapping: ResumeMapping | null; makeDefault: boolean }
  | { kind: 'mapping'; id: string; mapping: ResumeMapping; reading: MasterResume }
  | { kind: 'reading'; form: ResumeForm }

export default function ResumeSection({ mode, onSaved }: { mode: SectionMode; onSaved?: () => void | Promise<void> }) {
  const [list, setList] = useState<ResumeList | null>(null)
  const [legacy, setLegacy] = useState<MasterResume | null>(null) // the Master Resume, whatever the list says
  const [loadError, setLoadError] = useState('')
  const [view, setView] = useState<View>({ kind: 'list' })
  const [reading, setReading] = useState(false) // a draft is being read
  const [busyId, setBusyId] = useState('')
  const [rowError, setRowError] = useState<{ id: string; message: string } | null>(null)
  const [uploadError, setUploadError] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  async function refresh() {
    const [l, r] = await Promise.all([listResumes(), getResume()])
    setList(l)
    setLegacy(r)
  }

  useEffect(() => {
    Promise.all([listResumes(), getResume()])
      .then(([l, r]) => {
        setList(l)
        setLegacy(r)
      })
      .catch((e: unknown) => setLoadError(errText(e)))
  }, [])

  const loaded = list !== null
  const resumes = list?.resumes ?? []
  const defaultResume = resumes.find((r) => r.is_default)
  const phase2 = loaded && resumes.length === 0 && legacy !== null

  async function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    e.target.value = '' // so the same file can be chosen again
    if (!file) return
    setUploadError('')
    setReading(true)
    try {
      // A draft only: nothing is saved until Save is pressed.
      const draft = await draftResume(file)
      setView({
        kind: 'upload',
        draft,
        name: draft.filename.replace(/\.[^.]*$/, ''),
        form: toForm(draft.reading),
        mapping: draft.mapping,
        makeDefault: resumes.length === 0,
      })
    } catch (err) {
      setUploadError(errText(err))
    } finally {
      setReading(false)
    }
  }

  async function act(id: string, fn: () => Promise<void>) {
    setRowError(null)
    setBusyId(id)
    try {
      await fn()
      await refresh()
    } catch (err) {
      setRowError({ id, message: errText(err) })
    } finally {
      setBusyId('')
    }
  }

  async function checkMapping(id: string) {
    setRowError(null)
    setBusyId(id)
    try {
      const [mapping, resumeReading] = await Promise.all([getMapping(id), getResumeReading(id)])
      setView({ kind: 'mapping', id, mapping, reading: resumeReading })
    } catch (err) {
      setRowError({ id, message: errText(err) })
    } finally {
      setBusyId('')
    }
  }

  async function editReading() {
    setUploadError('')
    try {
      const r = await getResume()
      if (r) setView({ kind: 'reading', form: toForm(r) })
    } catch (err) {
      setUploadError(errText(err))
    }
  }

  async function save() {
    if (view.kind === 'upload') {
      await saveNewResume({
        upload_id: view.draft.upload_id,
        name: view.name,
        reading: fromForm(view.form),
        mapping: view.draft.kind === 'docx' ? view.mapping : null,
        make_default: view.makeDefault || resumes.length === 0,
      })
    } else if (view.kind === 'mapping') {
      await saveMapping(view.id, view.mapping)
    } else if (view.kind === 'reading') {
      await saveResume(fromForm(view.form))
    }
    setView({ kind: 'list' })
    await refresh()
    await onSaved?.()
  }

  const summary = defaultResume
    ? `${plural(resumes.length, 'resume', 'resumes')} · default: ${defaultResume.name}`
    : resumes.length
      ? plural(resumes.length, 'resume', 'resumes')
      : 'None yet'

  const canSave =
    loaded && !loadError && !reading && (view.kind === 'list' ? resumes.length > 0 || legacy !== null : true)

  const updateForm = (patch: Partial<ResumeForm>) => {
    if (view.kind === 'upload' || view.kind === 'reading') setView({ ...view, form: { ...view.form, ...patch } })
  }
  const backToList = () => setView({ kind: 'list' })

  return (
    <SectionCard
      title="Your resume"
      tip="This is the one master copy. Every tailored resume JobMe writes starts from it."
      summary={summary}
      mode={mode}
      onSave={save}
      canSave={canSave}
      onCancel={backToList}
    >
      {loadError && <div className="result bad">{loadError}</div>}
      {!loaded && !loadError && <p className="muted">Loading…</p>}
      <input ref={fileRef} type="file" accept={ACCEPT} hidden onChange={(e) => void onFile(e)} />
      {loaded && view.kind === 'list' && (
        <>
          {phase2 && <p className="result">Upload your resume file so JobMe can use its layout.</p>}
          {resumes.map((r) => (
            <div key={r.id}>
              <div className="row">
                <strong>{r.name}</strong>
                <span className="muted">
                  (.{r.kind}
                  {r.pages ? ` · ${plural(r.pages, 'page', 'pages')}` : ''})
                </span>
                {r.is_default && <span className="muted">Default</span>}
                {!r.is_default && (
                  <button disabled={busyId === r.id} onClick={() => void act(r.id, () => makeDefault(r.id))}>
                    Make default
                  </button>
                )}
                {r.kind === 'docx' && r.has_mapping && (
                  <button disabled={busyId === r.id} onClick={() => void checkMapping(r.id)}>
                    Check mapping
                  </button>
                )}
                <button className="danger" disabled={busyId === r.id} onClick={() => void act(r.id, () => removeResume(r.id))}>
                  Remove
                </button>
              </div>
              {rowError?.id === r.id && <div className="result bad">{rowError.message}</div>}
            </div>
          ))}
          {reading ? (
            <p role="status" className="muted">
              Reading your resume…
            </p>
          ) : (
            <>
              <div className="row">
                <button className="add" onClick={() => fileRef.current?.click()}>
                  Upload a resume
                </button>
                {(defaultResume || phase2) && <button onClick={() => void editReading()}>Edit what JobMe read</button>}
              </div>
              <span className="help">Word, PDF, text or Markdown files work.</span>
              <AddResumeFolder
                existingNames={resumes.map((r) => r.name)}
                onDone={async () => {
                  await refresh()
                  await onSaved?.()
                }}
              />
            </>
          )}
          {uploadError && <div className="result bad">{uploadError}</div>}
        </>
      )}
      {loaded && view.kind === 'upload' && (
        <>
          <label>
            Name
            <input value={view.name} onChange={(e) => setView({ ...view, name: e.target.value })} />
            <span className="help">For example Main or Healthcare.</span>
          </label>
          <p className="help">
            Check what JobMe read. This is what tailored resumes are built from when this resume is the default.
          </p>
          <ReadingForm form={view.form} update={updateForm} />
          {view.draft.kind === 'docx' && view.draft.map_error && <div className="result bad">{view.draft.map_error}</div>}
          {view.draft.kind === 'docx' && view.mapping && (
            <MappingReview
              mapping={view.mapping}
              // Bullet labels name jobs as JobMe first read them; Save follows any job moved in the form.
              reading={view.draft.reading}
              onChange={(m) => setView({ ...view, mapping: m })}
            />
          )}
          <label className="row">
            <input
              type="checkbox"
              checked={view.makeDefault || resumes.length === 0}
              disabled={resumes.length === 0}
              onChange={(e) => setView({ ...view, makeDefault: e.target.checked })}
            />
            Make this my default
          </label>
          <div className="row">
            <button onClick={backToList}>Cancel</button>
          </div>
        </>
      )}
      {loaded && view.kind === 'mapping' && (
        <>
          <MappingReview
            mapping={view.mapping}
            reading={view.reading}
            onChange={(m) => setView({ ...view, mapping: m })}
          />
          <div className="row">
            <button onClick={backToList}>Back</button>
          </div>
        </>
      )}
      {loaded && view.kind === 'reading' && (
        <>
          <ReadingForm form={view.form} update={updateForm} />
          <div className="row">
            <button onClick={backToList}>Back</button>
          </div>
        </>
      )}
    </SectionCard>
  )
}
