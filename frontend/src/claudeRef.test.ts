import { describe, expect, it } from 'vitest'
import { contactRef, followUpRef, jobRef } from './claudeRef.ts'

describe('references for Claude', () => {
  it('names the job the way the MCP tools read it', () => {
    expect(jobRef({ id: 123, employer: 'Acme', title: 'Staff Engineer' })).toBe('JobMe job 123: Acme – Staff Engineer')
  })
  it('trims a very long title to 80 characters', () => {
    const title = jobRef({ id: 1, employer: 'Acme', title: 'x'.repeat(200) }).split(' – ')[1]
    expect(title).toBe(`${'x'.repeat(79)}…`)
  })
  it('names a contact and a follow-up with their ids', () => {
    expect(contactRef({ id: 5, name: 'Jane Doe', employer: 'Acme' })).toBe('JobMe contact 5: Jane Doe (Acme)')
    expect(contactRef({ id: 6, name: null, employer: null })).toBe('JobMe contact 6: Unnamed contact')
    expect(followUpRef({ id: 9, type: 'Thank-you note', due_date: '2026-12-01' })).toBe(
      'JobMe follow-up 9: Thank-you note due 2026-12-01',
    )
  })
})
