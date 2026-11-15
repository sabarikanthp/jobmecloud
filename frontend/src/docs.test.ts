import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { configure } from './auth.ts'
import { DOCS_POLL_MS, makeDocs, openDoc } from './api.ts'

function reply(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

beforeEach(() => {
  configure(null)
  vi.useFakeTimers()
})
afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('makeDocs', () => {
  it('returns straight away when the server wrote the documents during the request', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(reply({ note: '1 page', folder: '/x' })))
    expect(await makeDocs(5)).toEqual({ note: '1 page', folder: '/x' })
  })

  it('waits for the documents worker and returns its note', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(reply({ status: 'generating' }, 202))
      .mockResolvedValueOnce(reply({ status: 'generating', note: null, folder: null, error: null }))
      .mockResolvedValueOnce(reply({ status: 'ready', note: '1 page, same as your resume', folder: '/apps/Acme', error: null }))
    vi.stubGlobal('fetch', fetchMock)
    const done = makeDocs(5, 'more data')
    await vi.advanceTimersByTimeAsync(DOCS_POLL_MS * 3)
    expect(await done).toEqual({ note: '1 page, same as your resume', folder: '/apps/Acme' })
    expect(fetchMock.mock.calls[1][0]).toBe('/api/jobs/5/docs/status')
  })

  it('throws the worker error message', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValueOnce(reply({ status: 'generating' }, 202))
        .mockResolvedValueOnce(reply({ status: 'error', note: null, folder: null, error: 'Add your resume first.' })),
    )
    const done = makeDocs(5)
    const failed = expect(done).rejects.toThrow('Add your resume first.')
    await vi.advanceTimersByTimeAsync(DOCS_POLL_MS * 2)
    await failed
  })

  it('gives up with a plain message when the worker never finishes', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation(async (url: string) =>
        url.endsWith('/docs') ? reply({ status: 'generating' }, 202) : reply({ status: 'generating', error: null }),
      ),
    )
    const done = makeDocs(5)
    const failed = expect(done).rejects.toThrow(/taking longer than expected/)
    await vi.advanceTimersByTimeAsync(7 * 60 * 1000)
    await failed
  })
})

describe('openDoc', () => {
  it('in the cloud asks for a download link and opens it', async () => {
    configure({ domain: 'login.example.com', clientId: 'c' })
    localStorage.setItem('jobmecloud.tokens', JSON.stringify({ access_token: 'A', expires_at: Date.now() / 1000 + 3600 }))
    const fetchMock = vi.fn().mockResolvedValue(reply({ url: 'https://s3.example/resume.docx', filename: 'resume.docx' }))
    vi.stubGlobal('fetch', fetchMock)
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    await openDoc(5, 'resume')
    expect(fetchMock.mock.calls[0][0]).toBe('/api/jobs/5/download')
    expect(open).toHaveBeenCalledWith('https://s3.example/resume.docx', '_blank')
  })
})
