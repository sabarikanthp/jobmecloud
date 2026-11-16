import { describe, expect, it } from 'vitest'
import { PAGES, jobHref, parseRoute, routeHash } from './route.ts'

describe('parseRoute', () => {
  it('an empty address is the Today page', () => {
    expect(parseRoute('')).toEqual({ page: 'Today', jobId: null })
    expect(parseRoute('#')).toEqual({ page: 'Today', jobId: null })
    expect(parseRoute('#/')).toEqual({ page: 'Today', jobId: null })
  })

  it('reads each page', () => {
    expect(parseRoute('#/today').page).toBe('Today')
    expect(parseRoute('#/jobs').page).toBe('Jobs')
    expect(parseRoute('#/follow-ups').page).toBe('Follow-ups')
    expect(parseRoute('#/dashboard').page).toBe('Dashboard')
    expect(parseRoute('#/settings').page).toBe('Settings')
  })

  it('reads a job address', () => {
    expect(parseRoute('#/jobs/123')).toEqual({ page: 'Jobs', jobId: 123 })
  })

  it('ignores anything after the job id', () => {
    expect(parseRoute('#/jobs/12/whatever')).toEqual({ page: 'Jobs', jobId: 12 })
  })

  it('treats a bad job id as the jobs list, never as a job', () => {
    for (const bad of ['#/jobs/abc', '#/jobs/0', '#/jobs/-5', '#/jobs/1.5', '#/jobs/12abc', '#/jobs/']) {
      expect(parseRoute(bad)).toEqual({ page: 'Jobs', jobId: null })
    }
  })

  it('ignores a job id on any page but Jobs', () => {
    expect(parseRoute('#/settings/7')).toEqual({ page: 'Settings', jobId: null })
  })

  it('treats an unknown page as Today', () => {
    expect(parseRoute('#/nope')).toEqual({ page: 'Today', jobId: null })
    expect(parseRoute('#/jobs-evil')).toEqual({ page: 'Today', jobId: null })
  })

  it('is not case sensitive', () => {
    expect(parseRoute('#/JOBS/9')).toEqual({ page: 'Jobs', jobId: 9 })
  })
})

describe('routeHash and jobHref', () => {
  it('every page round-trips through its address', () => {
    for (const page of PAGES) expect(parseRoute(routeHash(page))).toEqual({ page, jobId: null })
  })

  it('a job round-trips through its address', () => {
    expect(routeHash('Jobs', 42)).toBe('#/jobs/42')
    expect(parseRoute(routeHash('Jobs', 42))).toEqual({ page: 'Jobs', jobId: 42 })
  })

  it('a job id is only used with the Jobs page', () => {
    expect(routeHash('Settings', 42)).toBe('#/settings')
  })

  it('jobHref is the address a link to a job points at', () => {
    expect(jobHref(5)).toBe('#/jobs/5')
  })
})
