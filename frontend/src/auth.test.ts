import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { challengeFor, configure, getToken, handleCallback, login, nav, rememberWhere, restoreWhere } from './auth.ts'
import { getProviders } from './api.ts'

const CONFIG = { domain: 'login.example.com', clientId: 'client123' }
const SESSION = 'jobmecloud.tokens'

function signedIn(expiresInSeconds = 3600) {
  localStorage.setItem(
    SESSION,
    JSON.stringify({ access_token: 'ACCESS', refresh_token: 'REFRESH', expires_at: Date.now() / 1000 + expiresInSeconds }),
  )
}

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  configure(CONFIG)
})
afterEach(() => vi.restoreAllMocks())

describe('pkce', () => {
  it('challenge is the base64url sha256 of the verifier (RFC 7636 appendix B)', async () => {
    const challenge = await challengeFor('dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk')
    expect(challenge).toBe('E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM')
  })
})

describe('api calls', () => {
  it('adds the bearer token', async () => {
    signedIn()
    const fetchMock = vi.fn().mockResolvedValue(new Response('[]', { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    await getProviders()
    const headers = fetchMock.mock.calls[0][1].headers as Record<string, string>
    expect(headers.Authorization).toBe('Bearer ACCESS')
  })

  it('a 401 sends the user to sign in', async () => {
    signedIn()
    const go = vi.spyOn(nav, 'to').mockImplementation(() => {})
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 401 })))
    await expect(getProviders()).rejects.toThrow()
    expect(go).toHaveBeenCalledOnce()
    expect(go.mock.calls[0][0]).toContain('https://login.example.com/oauth2/authorize')
    expect(go.mock.calls[0][0]).toContain('code_challenge_method=S256')
  })
})

describe('tokens', () => {
  it('refreshes an access token that is about to expire', async () => {
    signedIn(10)
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify({ access_token: 'NEW', expires_in: 3600 }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    expect(await getToken()).toBe('NEW')
    expect(String(fetchMock.mock.calls[0][1].body)).toContain('grant_type=refresh_token')
  })
})

describe('returning to the address you were on', () => {
  beforeEach(() => {
    window.location.hash = ''
  })

  it('remembers an app address and puts it back', () => {
    window.location.hash = '#/jobs/12'
    rememberWhere()
    window.location.hash = ''
    restoreWhere()
    expect(window.location.hash).toBe('#/jobs/12')
  })

  it('remembers nothing for an empty or foreign fragment', () => {
    window.location.hash = '#section'
    rememberWhere()
    window.location.hash = ''
    restoreWhere()
    expect(window.location.hash).toBe('')
  })

  it('only restores an app address, never anything else that was stored', () => {
    sessionStorage.setItem('jobmecloud.return', 'javascript:alert(1)')
    restoreWhere()
    expect(window.location.hash).toBe('')
    expect(sessionStorage.getItem('jobmecloud.return')).toBeNull()
  })

  it('starting to sign in remembers where you were', async () => {
    vi.spyOn(nav, 'to').mockImplementation(() => {})
    window.location.hash = '#/jobs/12'
    await login()
    window.location.hash = ''
    restoreWhere()
    expect(window.location.hash).toBe('#/jobs/12')
  })

  it('finishing sign in puts you back on that address', async () => {
    vi.spyOn(nav, 'to').mockImplementation(() => {})
    window.location.hash = '#/jobs/12'
    await login()
    const state = sessionStorage.getItem('jobmecloud.pkce.state')!
    window.history.replaceState({}, '', `/?code=abc&state=${state}`) // Cognito sends you back without the fragment
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ access_token: 'A', expires_in: 3600 }))))
    await handleCallback()
    expect(window.location.hash).toBe('#/jobs/12')
    expect(window.location.search).toBe('')
  })
})

describe('consent link through sign-in', () => {
  it('keeps the whole #/connect request, query included, across the trip to the sign-in page', () => {
    window.location.hash = '#/connect?client_id=abc&state=x%20y&redirect_uri=https%3A%2F%2Fchatgpt.com%2Fcb'
    const before = window.location.hash
    rememberWhere()
    window.history.replaceState({}, '', window.location.pathname) // what handleCallback does on return
    expect(window.location.hash).toBe('')
    restoreWhere()
    expect(window.location.hash).toBe(before)
  })
})
