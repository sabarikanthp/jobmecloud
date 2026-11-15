import { useState } from 'react'
import { commitTracker, previewTracker } from '../api.ts'
import SectionCard, { type SectionMode } from '../components/SectionCard.tsx'
import SpreadsheetImport, { type ImportField } from '../components/SpreadsheetImport.tsx'

const FIELDS: ImportField[] = [
  { key: 'employer', label: 'Employer', help: 'The company name. Required.', required: true },
  { key: 'title', label: 'Job title', help: 'The name of the job. Required.', required: true },
  { key: 'requisition_id', label: 'Requisition or job ID', help: "The employer's number for the job, if your file has one." },
  { key: 'location', label: 'Location', help: 'Where the job is.' },
  { key: 'status', label: 'Status', help: 'For example applied, interviewing or rejected.' },
  { key: 'applied_date', label: 'Date applied', help: 'When you applied.' },
  { key: 'url', label: 'Link', help: 'The web address of the job posting.' },
  { key: 'notes', label: 'Notes', help: 'Anything you wrote down about the job.' },
]

export default function ImportSection({ mode, onSaved }: { mode: SectionMode; onSaved?: () => void | Promise<void> }) {
  const [pending, setPending] = useState(false)

  return (
    <SectionCard
      title="Import past jobs"
      tip="Importing is optional. It only helps JobMe skip jobs you have already seen."
      summary="Upload a spreadsheet of past jobs"
      mode={mode}
      saveLabel="Continue"
      canSave={!pending}
      onSave={async () => {
        await onSaved?.()
      }}
    >
      <p>
        Have a spreadsheet of jobs you've already looked at or applied to? JobMe will use it to avoid showing you the same
        jobs again.
      </p>
      <SpreadsheetImport
        fields={FIELDS}
        preview={previewTracker}
        commit={commitTracker}
        sheetHelp="Which sheet of the file holds your jobs."
        requiredHelp="Choose the columns for Employer and Job title to import."
        onPendingChange={setPending}
      />
    </SectionCard>
  )
}
