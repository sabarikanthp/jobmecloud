import { authEnabled, getToken, login } from './auth.ts'

export type ProviderKind = 'anthropic' | 'openai_compatible'
export type StructuredOutput = 'native' | 'prompt'
export type SearchBackend = 'builtin' | 'tavily' | 'brave'

export interface ProviderConfig {
  id: string
  kind: ProviderKind
  label: string
  base_url: string | null
  structured_output: StructuredOutput
}

export interface ProviderOut extends ProviderConfig {
  has_key: boolean
}

export interface ConnectionResult {
  ok: boolean
  message: string
}

export interface SearchSaved {
  backend: SearchBackend
  has_key: boolean
}

// Settings has more fields than the screen edits; they are passed through untouched.
export interface Settings {
  search_backend: SearchBackend
  providers: ProviderConfig[]
  [key: string]: unknown
}

export interface SetupState {
  completed: number[]
  skipped: number[]
  next_step: number
  finished: boolean
}

export interface UserProfile {
  name: string
  email: string
  phone: string
  location: string
  linkedin_url: string
  links: string[]
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = init?.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }
  const token = await getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  let res: Response
  try {
    res = await fetch(`/api${path}`, { ...init, headers })
  } catch {
    throw new Error("Couldn't reach JobMeCloud. Check your connection and try again.")
  }
  if (res.status === 401 && authEnabled()) {
    await login()
    throw new Error('Your session has ended. Signing you in again…')
  }
  if (!res.ok) {
    let detail = ''
    try {
      const body = await res.json()
      if (typeof body.detail === 'string') detail = body.detail
      else if (Array.isArray(body.detail))
        detail = body.detail
          .map((d: { msg?: unknown }) => (typeof d?.msg === 'string' ? d.msg : ''))
          .filter(Boolean)
          .join(' ')
    } catch {
      /* ignore */
    }
    throw new Error(detail || `Something went wrong (error ${res.status}).`)
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

export const getProviders = () => request<ProviderOut[]>('/providers')

export const saveProvider = (p: ProviderConfig, apiKey?: string) =>
  request<ProviderOut>(`/providers/${encodeURIComponent(p.id)}`, {
    method: 'PUT',
    body: JSON.stringify({ ...p, api_key: apiKey ? apiKey : null }),
  })

export const deleteProvider = (id: string) =>
  request<void>(`/providers/${encodeURIComponent(id)}`, { method: 'DELETE' })

export const testProvider = (id: string, model: string) =>
  request<ConnectionResult>(`/providers/${encodeURIComponent(id)}/test`, {
    method: 'POST',
    body: JSON.stringify({ model }),
  })

export const getSearch = () => request<SearchSaved>('/search')

export const saveSearch = (backend: SearchBackend, apiKey?: string) =>
  request<SearchSaved>('/search', {
    method: 'PUT',
    body: JSON.stringify({ backend, api_key: apiKey ? apiKey : null }),
  })

export const testSearch = () => request<ConnectionResult>('/search/test', { method: 'POST' })

export const getSettings = () => request<Settings>('/settings')

export const saveSettings = (s: Settings) =>
  request<Settings>('/settings', { method: 'PUT', body: JSON.stringify(s) })

export const getSetup = () => request<SetupState>('/setup')

export const completeStep = (n: number) =>
  request<SetupState>(`/setup/${n}/complete`, { method: 'POST' })

export const skipStep = (n: number) => request<SetupState>(`/setup/${n}/skip`, { method: 'POST' })

export const getUser = () => request<UserProfile>('/profile/user')

export const saveUser = (u: UserProfile) =>
  request<UserProfile>('/profile/user', { method: 'PUT', body: JSON.stringify(u) })

export interface StepModel {
  provider_id: string
  model: string | null
}
export type Steps = Record<string, StepModel>

export interface ModelsInfo {
  steps: { id: string; label: string; help: string }[]
  recommended: Record<ProviderKind, string[]>
  local_note: string
}

export const getModels = () => request<ModelsInfo>('/models')

export const applyDefaultSteps = (providerId: string, model: string | null) =>
  request<Steps>('/steps/defaults', {
    method: 'POST',
    body: JSON.stringify({ provider_id: providerId, model }),
  })

export interface ResumeRole {
  employer: string
  title: string
  start: string
  end: string
  location: string
  bullets: string[]
}
export interface ResumeEducation {
  school: string
  degree: string
  field: string
  year: string
}
export interface ResumeCertification {
  name: string
  issuer: string
  year: string
}
export interface MasterResume {
  summary: string
  roles: ResumeRole[]
  skills: string[]
  education: ResumeEducation[]
  certifications: ResumeCertification[]
}

export const getResume = () => request<MasterResume | null>('/profile/resume')

export const saveResume = (r: MasterResume) =>
  request<MasterResume>('/profile/resume', { method: 'PUT', body: JSON.stringify(r) })

export interface ResumeEntry {
  id: string
  name: string
  filename: string
  kind: string
  uploaded_at: string
  has_mapping: boolean
  is_default: boolean
  pages: number | null
}
export interface ResumeList {
  default_id: string | null
  resumes: ResumeEntry[]
}
export interface MappedParagraph {
  index: number
  text: string
  label: string
}
export interface ResumeMapping {
  paragraphs: MappedParagraph[]
  role_keys?: string[]
  stale?: boolean
}
export interface ResumeDraft {
  upload_id: string
  kind: string
  filename: string
  reading: MasterResume
  mapping: ResumeMapping | null
  map_error: string | null
}
export interface NewResumeBody {
  upload_id: string
  name: string
  reading: MasterResume
  mapping: ResumeMapping | null
  make_default: boolean
}

export const listResumes = () => request<ResumeList>('/resumes')

// Returns a draft only. Nothing is saved until saveNewResume is called.
export const draftResume = (file: File) => {
  const body = new FormData()
  body.append('file', file)
  return request<ResumeDraft>('/resumes/draft', { method: 'POST', body })
}

export const saveNewResume = (body: NewResumeBody) =>
  request<ResumeEntry>('/resumes', { method: 'POST', body: JSON.stringify(body) })

export const getResumeReading = (id: string) =>
  request<MasterResume>(`/resumes/${encodeURIComponent(id)}/reading`)

export const getMapping = (id: string) => request<ResumeMapping>(`/resumes/${encodeURIComponent(id)}/mapping`)

export const saveMapping = (id: string, m: ResumeMapping) =>
  request<ResumeMapping>(`/resumes/${encodeURIComponent(id)}/mapping`, { method: 'PUT', body: JSON.stringify(m) })

export const makeDefault = (id: string) =>
  request<void>(`/resumes/${encodeURIComponent(id)}/default`, { method: 'POST' })

export const removeResume = (id: string) =>
  request<void>(`/resumes/${encodeURIComponent(id)}`, { method: 'DELETE' })


export type WorkMode = 'remote' | 'hybrid' | 'onsite'
export type DayKey = 'mon' | 'tue' | 'wed' | 'thu' | 'fri' | 'sat' | 'sun'
export interface SearchProfile {
  target_roles: string[]
  positioning: string
  locations: string[]
  radius_miles: number | null
  work_modes: WorkMode[]
  min_base_pay: number | null
  excluded_employers: string[]
  deal_breakers: string[]
  warnings: string[]
  max_commute_miles: number | null
  max_posted_days: number | null
  do_not_claim: string[]
  rotation: Partial<Record<DayKey, string>>
}

export const getSearchProfile = () => request<SearchProfile>('/profile/search')

export const saveSearchProfile = (p: SearchProfile) =>
  request<SearchProfile>('/profile/search', { method: 'PUT', body: JSON.stringify(p) })

// Returns a draft only. Nothing is saved until saveSearchProfile is called.
export const importSearchNotes = (file: File) => {
  const body = new FormData()
  body.append('file', file)
  return request<SearchProfile>('/profile/search/import', { method: 'POST', body })
}

export interface WatchlistEmployer {
  name: string
  priority: number
  careers_url: string | null
  rotation_day: DayKey | null
}
export interface WatchlistRow extends WatchlistEmployer {
  id: number
  last_checked_at: string | null
}

export const listWatchlist = () => request<WatchlistRow[]>('/watchlist')

export const addWatchlist = (e: WatchlistEmployer) =>
  request<WatchlistRow>('/watchlist', { method: 'POST', body: JSON.stringify(e) })

export const updateWatchlist = (id: number, e: WatchlistEmployer) =>
  request<WatchlistRow>(`/watchlist/${id}`, { method: 'PUT', body: JSON.stringify(e) })

export const deleteWatchlist = (id: number) => request<void>(`/watchlist/${id}`, { method: 'DELETE' })

// Spreadsheet imports (past jobs, employers to watch) share one upload -> map columns -> commit flow.
export type ColumnMapping = Record<string, string | null>

export interface ImportSheet {
  name: string
  columns: string[]
  sample_rows: string[][]
  suggested_mapping: ColumnMapping
}

export interface ImportPreview {
  upload_id: string
  sheets: ImportSheet[]
}

export interface ImportCommit {
  upload_id: string
  sheet: string
  mapping: ColumnMapping
}

export interface ImportResult {
  imported: number
  duplicates: number
  skipped: number
  message: string
}

const previewSheet = (path: string, file: File) => {
  const body = new FormData()
  body.append('file', file)
  return request<ImportPreview>(path, { method: 'POST', body })
}
const commitSheet = (path: string, body: ImportCommit) =>
  request<ImportResult>(path, { method: 'POST', body: JSON.stringify(body) })

export const previewTracker = (file: File) => previewSheet('/import/tracker/preview', file)
export const commitTracker = (body: ImportCommit) => commitSheet('/import/tracker/commit', body)
export const previewWatchlistImport = (file: File) => previewSheet('/import/watchlist/preview', file)
export const commitWatchlistImport = (body: ImportCommit) => commitSheet('/import/watchlist/commit', body)

export type RunOutcome = 'new' | 'duplicate' | 'excluded' | 'matched' | 'prepared' | 'closed'

export interface RunInfo {
  id: number
  trigger: string
  started_at: string
  finished_at: string | null
  stage: string | null
  running: boolean
  found: number
  new: number
  excluded: number
  matched: number
  prepared: number
  errors: string[]
  est_cost: number
}

export interface JobSummary {
  id: number
  employer: string
  title: string
  location: string | null
  work_mode: string | null
  pay_min: number | null
  pay_max: number | null
  pay_verified: boolean | null
  apply_url: string | null
  source: string | null
  match_score: number | null
  hard_rules: { rule: string; passed: boolean; note: string }[]
  flags: string[]
  reasons: string | null
  gaps: string | null
  liveness: string | null
  status: string
  repost_of_id: number | null
  docs_folder: string | null
  docs_note: string | null
  docs_error: string | null
  allowed_next: string[]
}

export interface RunJobRow {
  outcome: RunOutcome
  job: JobSummary
}

export const startRun = () => request<{ run_id: number }>('/runs', { method: 'POST' })

export const getLatestRun = () => request<RunInfo | null>('/runs/latest')

export interface InboundEmailInfo {
  received_at: string
  status: string
  note: string | null
  run_id: number | null
}

export const getInbound = () => request<{ emails: InboundEmailInfo[] }>('/inbound')

export const getRunJobs = (id: number) => request<RunJobRow[]>(`/runs/${id}/jobs`)

export interface DocsResult {
  note: string | null
  folder: string
}

export interface DocsStatus {
  status: 'generating' | 'ready' | 'error' | null
  note: string | null
  folder: string | null
  error: string | null
}

export const DOCS_POLL_MS = 3000
const DOCS_GIVE_UP_MS = 6 * 60 * 1000 // a bit over the documents worker's own 5-minute limit

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

// In AWS the documents are written by a background worker: start it, then wait for it to finish.
// Locally the server writes them during the request and answers with the result straight away.
export async function makeDocs(id: number, feedback?: string | null): Promise<DocsResult> {
  const first = await request<DocsResult | { status: string }>(`/jobs/${id}/docs`, {
    method: 'POST',
    body: JSON.stringify({ feedback: feedback ? feedback : null }),
  })
  if (!('status' in first)) return first
  const deadline = Date.now() + DOCS_GIVE_UP_MS
  while (Date.now() < deadline) {
    await sleep(DOCS_POLL_MS)
    const s = await request<DocsStatus>(`/jobs/${id}/docs/status`)
    if (s.status === 'ready') return { note: s.note, folder: s.folder ?? '' }
    if (s.status === 'error') throw new Error(s.error || 'Writing the documents failed.')
  }
  throw new Error('Writing the documents is taking longer than expected. Check back in a few minutes.')
}

export const useAsIs = (id: number, resumeId: string) =>
  request<DocsResult>(`/jobs/${id}/as-is`, { method: 'POST', body: JSON.stringify({ resume_id: resumeId }) })

// In AWS the files live in S3, so "open" means download through a short-lived link.
export async function openDoc(id: number, what: 'resume' | 'cover_letter' | 'folder'): Promise<void> {
  if (authEnabled()) {
    if (what === 'folder') return
    const { url } = await request<{ url: string; filename: string }>(`/jobs/${id}/download`, {
      method: 'POST',
      body: JSON.stringify({ what }),
    })
    window.open(url, '_blank')
    return
  }
  await request<void>(`/jobs/${id}/open`, { method: 'POST', body: JSON.stringify({ what }) })
}

// ---- Tracking ----

// Turn a YYYY-MM-DD string into "14 Mar 2026". Split by hand: new Date('2026-03-14') is UTC and can show the wrong day.
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
export function fmtDate(s: string | null): string {
  if (!s) return ''
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s)
  if (!m) return s
  const month = MONTHS[Number(m[2]) - 1]
  if (!month) return s
  return `${Number(m[3])} ${month} ${m[1]}`
}

export interface JobRow {
  allowed_next: string[] // the status moves this job allows, so the list can offer them
  id: number
  employer: string
  title: string
  status: string
  match_score: number | null
  source: string | null
  location: string | null
  work_mode: string | null
  requisition_id: string | null
  pay_min: number | null
  pay_max: number | null
  pay_verified: boolean | null
  first_seen_date: string | null
  applied_date: string | null
  first_response_date: string | null
  outcome_date: string | null
  flags: string[]
  apply_url: string | null
  linkedin: boolean
  docs_ready: boolean
  has_open_followup: boolean
  next_followup_due: string | null
  /** Custom values for the columns asked for with `fields`: field id (as text) to value. */
  fields?: Record<string, string>
}

export interface TimelineEntry {
  at: string
  actor: string
  action: string
  entity_type: string
  from_value: string | null
  to_value: string | null
  note: string | null
}

export interface ContactRow {
  id: number
  job_id: number | null
  employer: string | null
  name: string | null
  role: string | null
  link: string | null
  relationship: string | null
  status: string | null
  notes: string | null
  open_followups: number
  job_title: string | null
}

export interface FollowUpRow {
  id: number
  job_id: number | null
  contact_id: number | null
  type: string
  due_date: string
  status: string
  bucket: 'overdue' | 'today' | 'upcoming' | 'done'
  note: string | null
  outcome_note: string | null
  completed_date: string | null
  employer: string | null
  job_title: string | null
  contact_name: string | null
}

export interface InterviewRow {
  id: number
  date: string | null
  stage: string | null
  notes: string | null
}

export interface JobDetail extends JobRow {
  description: string | null
  reasons: string | null
  gaps: string | null
  hard_rules: { rule: string; passed: boolean; note: string }[] | Record<string, unknown>
  notes: string | null
  skip_reason: string | null
  skip_note: string | null
  liveness: string | null
  repost_of_id: number | null
  docs_folder: string | null
  docs_note: string | null
  docs_error: string | null
  allowed_next: string[]
  fields: Record<string, string>
  contacts: ContactRow[]
  followups: FollowUpRow[]
  interviews: InterviewRow[]
  timeline: TimelineEntry[]
}

export interface StatusResult {
  id: number
  status: string
  applied_date: string | null
  first_response_date: string | null
  outcome_date: string | null
  allowed_next: string[]
  follow_up_id: number | null
}

export interface StatusBody {
  status: string
  date?: string | null
  skip_reason?: string | null
  skip_note?: string | null
  note?: string | null
}

export interface DashboardData {
  funnel: { found: number; matched: number; applied: number; interviewing: number; offer: number }
  weekly: { week_start: string; applied: number }[]
  response: { applied: number; responded: number; rate: number | null }
  skip_reasons: { reason: string; count: number }[]
  sources: { source: string; count: number }[]
  followups: { overdue: FollowUpRow[]; this_week: FollowUpRow[] }
}

export interface JobListParams {
  status?: string[]
  min_score?: number
  q?: string
  source?: string
  from?: string
  to?: string
  flag?: string
  has_followup?: boolean
  sort?: 'first_seen' | 'match' | 'employer' | 'status' | 'applied' | `field:${number}`
  /** Custom field ids whose values to include in each row. */
  fields?: number[]
  /** Custom field filters, each `<field id>:<value>`. */
  cf?: string[]
  dir?: 'asc' | 'desc'
  limit?: number
  offset?: number
}

function query(params: object): string {
  const q = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === '') continue
    if (Array.isArray(v)) v.forEach((x) => q.append(k, String(x)))
    else q.set(k, String(v))
  }
  const s = q.toString()
  return s ? `?${s}` : ''
}

const post = (body: unknown) => ({ method: 'POST', body: JSON.stringify(body) })

export const listJobs = (params: JobListParams = {}) =>
  request<{ total: number; rows: JobRow[] }>(`/jobs${query(params)}`)

export const getJobFacets = () =>
  request<{ sources: string[]; statuses: Record<string, number> }>('/jobs/facets')

export const getJob = (id: number) => request<JobDetail>(`/jobs/${id}`)

export const setStatus = (id: number, body: StatusBody) => request<StatusResult>(`/jobs/${id}/status`, post(body))

export const reopenJob = (id: number, note?: string | null) =>
  request<StatusResult>(`/jobs/${id}/reopen`, post({ note: note ? note : null }))

export const patchJob = (
  id: number,
  body: { notes?: string | null; applied_date?: string | null; first_response_date?: string | null; outcome_date?: string | null },
) => request<StatusResult>(`/jobs/${id}`, { method: 'PATCH', body: JSON.stringify(body) })

export const addJob = (body: { employer: string; title: string; apply_url?: string | null; location?: string | null; notes?: string | null }) =>
  request<{ id: number; status: string }>('/jobs', post(body))

export const listFollowUps = (params: { bucket?: FollowUpRow['bucket']; job_id?: number; contact_id?: number } = {}) =>
  request<FollowUpRow[]>(`/followups${query(params)}`)

export const addFollowUp = (body: { type: string; due_date: string; job_id?: number | null; contact_id?: number | null; note?: string | null }) =>
  request<FollowUpRow>('/followups', post(body))

export type FollowUpAction = 'done' | 'snooze' | 'reschedule' | 'cancel'

export const followUpAction = (id: number, action: FollowUpAction, body: { outcome_note?: string | null; until?: string; due_date?: string } = {}) =>
  request<FollowUpRow>(`/followups/${id}/${action}`, post(body))

export interface ContactBody {
  name: string
  job_id?: number | null
  employer?: string | null
  role?: string | null
  link?: string | null
  relationship?: string | null
  status?: string | null
  notes?: string | null
}

export const listContacts = (params: { job_id?: number; q?: string } = {}) =>
  request<ContactRow[]>(`/contacts${query(params)}`)

export const saveContact = (id: number | null, body: ContactBody) =>
  id === null
    ? request<ContactRow>('/contacts', post(body))
    : request<ContactRow>(`/contacts/${id}`, { method: 'PUT', body: JSON.stringify(body) })

export const deleteContact = (id: number) => request<void>(`/contacts/${id}`, { method: 'DELETE' })

export interface InterviewBody {
  date?: string | null
  stage?: string | null
  notes?: string | null
}

export interface InterviewResult {
  id: number
  job_id: number
  date: string | null
  stage: string | null
  notes: string | null
  status_changed: boolean
}

export const addInterview = (jobId: number, body: InterviewBody) =>
  request<InterviewResult>(`/jobs/${jobId}/interviews`, post(body))

export const saveInterview = (id: number, body: InterviewBody) =>
  request<InterviewResult>(`/interviews/${id}`, { method: 'PUT', body: JSON.stringify(body) })

export const deleteInterview = (id: number) => request<void>(`/interviews/${id}`, { method: 'DELETE' })

export const getDashboard = (weeks = 12) => request<DashboardData>(`/dashboard${query({ weeks })}`)

export type JobFieldType = 'text' | 'number' | 'date' | 'choice'

export interface JobField {
  id: number
  name: string
  type: JobFieldType
  choices: string[]
  position: number
  used: number
}

export const getJobFields = () => request<JobField[]>('/job-fields')

export const createJobField = (body: { name: string; type: JobFieldType; choices?: string[] }) =>
  request<JobField>('/job-fields', post(body))

export const updateJobField = (id: number, body: { name?: string; choices?: string[]; position?: number }) =>
  request<JobField>(`/job-fields/${id}`, { method: 'PATCH', body: JSON.stringify(body) })

export const deleteJobField = (id: number) =>
  request<{ deleted_values: number }>(`/job-fields/${id}`, { method: 'DELETE' })

export const setJobFields = (jobId: number, values: Record<number, string>) =>
  request<{ fields: Record<string, string> }>(`/jobs/${jobId}/fields`, {
    method: 'PUT',
    body: JSON.stringify({ values }),
  })

export type SheetKind = 'jobs' | 'applications' | 'contacts'

export interface SheetKindField {
  key: string
  label: string
  help: string
  required: boolean
}

export interface SheetInfo {
  name: string
  columns: string[]
  sample_rows: string[][]
  guessed_kind: SheetKind
  suggested: Record<SheetKind, ColumnMapping>
  /** The custom field JobMe would suggest for each column: its name, type and options. */
  columns_info: Record<string, { name: string; type: JobFieldType; choices: string[] }>
}

export interface SheetPreview {
  upload_id: string
  kinds: Record<SheetKind, SheetKindField[]>
  sheets: SheetInfo[]
}

export interface KeepAs {
  field_id?: number
  new?: { name: string; type: JobFieldType; choices: string[] }
}

export interface SheetImportBody {
  upload_id: string
  sheet: string
  kind: SheetKind
  mapping: ColumnMapping
  keep: Record<string, KeepAs>
  /** A status word (lower case) to a JobMe status, or '' for "Don't set". */
  status_words: Record<string, string>
  dry_run: boolean
}

export interface SheetReport {
  counts: { new: number; updated: number; unchanged: number; left_out: number }
  attention: { row: number; reason: string }[]
  words: { word: string; count: number; status: string }[]
  sample: { row: number; employer: string; title: string; action: string; status: string }[]
  message: string
}

export const sheetPreview = (file: File) => {
  const body = new FormData()
  body.append('file', file)
  return request<SheetPreview>('/import/sheet/preview', { method: 'POST', body })
}

export const sheetImport = (body: SheetImportBody) =>
  request<SheetReport>('/import/sheet', post(body))

export interface ScheduleLastRun {
  started_at: string
  finished_at: string | null
  found: number
  new: number
  matched: number
  errors: string[]
}

export interface ScheduleStatus {
  supported: boolean
  enabled: boolean
  next_run: string | null
  days: string[]
  times: string[]
  last_run: ScheduleLastRun | null
}

export const getSchedule = () => request<ScheduleStatus>('/schedule')

export const scheduleOn = (body: { days: string[]; times: string[] }) =>
  request<{ enabled: boolean }>('/schedule/on', post(body))

export const scheduleOff = () => request<{ enabled: boolean }>('/schedule/off', post({}))
