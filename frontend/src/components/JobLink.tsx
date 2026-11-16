import type { ReactNode } from 'react'
import { jobHref } from '../route.ts'

// A real link to a job. A plain click opens it here; right click, Ctrl or Cmd + click, or middle click opens it in
// a new tab, because the job has an address of its own.
export default function JobLink({ id, children }: { id: number; children: ReactNode }) {
  return (
    <a className="link" href={jobHref(id)}>
      {children}
    </a>
  )
}
