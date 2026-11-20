// Short references that are pasted into a Claude chat. The job one is understood by the get_job tool.

const MAX_TITLE = 80

export const jobRef = (job: { id: number; employer: string; title: string }): string => {
  const title = job.title.length > MAX_TITLE ? `${job.title.slice(0, MAX_TITLE - 1)}…` : job.title
  return `JobMe job ${job.id}: ${job.employer} – ${title}`
}

export const contactRef = (c: { id: number; name: string | null; employer: string | null }): string =>
  `JobMe contact ${c.id}: ${c.name || 'Unnamed contact'}${c.employer ? ` (${c.employer})` : ''}`

export const followUpRef = (f: { id: number; type: string; due_date: string }): string =>
  `JobMe follow-up ${f.id}: ${f.type} due ${f.due_date}`
