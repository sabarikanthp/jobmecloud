import { describe, expect, it } from 'vitest'
import page from '../index.html?raw'

// Phones (iPhone 16 Pro: 402 x 874 points) cannot show a wide table, so every table stacks into cards there.
const sources = import.meta.glob(['./**/*.tsx', '!./**/*.test.tsx'], { query: '?raw', import: 'default', eager: true })

describe('mobile layout', () => {
  it('draws under the iPhone safe areas so the styles can pad around them', () => {
    expect(page).toContain('viewport-fit=cover')
  })

  it('marks every table to stack on a narrow screen', () => {
    const tables = Object.entries(sources).flatMap(([file, text]) =>
      [...(text as string).matchAll(/<table\b[^>]*>/g)].map((m) => `${file}: ${m[0]}`),
    )
    expect(tables.length).toBeGreaterThan(0)
    expect(tables.filter((t) => !/className="[^"]*\bstack\b/.test(t))).toEqual([])
  })
})
