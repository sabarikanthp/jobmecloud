import type { JobSummary } from '../api.ts'

export function ApplyLink({ job, label = 'Apply' }: { job: JobSummary; label?: string }) {
  if (!job.apply_url) return null
  return (
    <a href={job.apply_url} target="_blank" rel="noreferrer">
      {label}
    </a>
  )
}

export function Chips({ flags }: { flags: string[] }) {
  return (
    <>
      {flags.map((f) => (
        <span className="chip" key={f}>
          {f}
        </span>
      ))}
    </>
  )
}
