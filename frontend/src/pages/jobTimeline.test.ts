import { describe as suite, expect, it } from 'vitest'
import { describe } from './jobTimeline.ts'

const entry = (actor: string) =>
  ({ action: 'status_changed', from_value: 'New', to_value: 'Applied', actor, note: null }) as never

suite('timeline actor labels', () => {
  it('names the Claude key that made a change', () => {
    expect(describe(entry('claude:Desktop'))).toContain('(by Claude: Desktop)')
  })
  it('still marks automatic changes', () => {
    expect(describe(entry('system'))).toContain('(automatic)')
  })
  it('leaves your own changes plain', () => {
    expect(describe(entry('user'))).not.toContain('(')
  })
})
