// Sign-in with Cognito's hosted login: authorization-code flow with PKCE, no client secret.
// /config.json (written at deploy) says where to sign in. Without it (local development) sign-in is off.

export interface AuthConfig {
  domain: string // e.g. jobmecloud-123456789012.auth.us-east-1.amazoncognito.com
  clientId: string
}

interface Tokens {
  access_token: string
  refresh_token?: string
  expires_at: number // seconds since the epoch
}

const SESSION_KEY = 'jobmecloud.tokens'
const VERIFIER_KEY = 'jobmecloud.pkce.verifier'
const STATE_KEY = 'jobmecloud.pkce.state'
const REFRESH_MARGIN_SECONDS = 60

let config: AuthConfig | null = null

// Tests replace `to`; in the browser it leaves the page for the sign-in screen.
export const nav = { to: (url: string) => window.location.assign(url) }

export function configure(next: AuthConfig | null) {
  config = next
}

export const authEnabled = () => config !== null

export async function loadConfig(): Promise<void> {
  try {
    const res = await fetch('/config.json')
    const body = await res.json()
    if (body && typeof body.domain === 'string' && typeof body.clientId === 'string') {
      config = { domain: body.domain, clientId: body.clientId }
    }
  } catch {
    config = null
  }
}

function base64url(bytes: Uint8Array): string {
  let binary = ''
  bytes.forEach((b) => (binary += String.fromCharCode(b)))
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

function randomString(): string {
  return base64url(crypto.getRandomValues(new Uint8Array(32)))
}

export async function challengeFor(verifier: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier))
  return base64url(new Uint8Array(digest))
}

const redirectUri = () => `${window.location.origin}/`

function readTokens(): Tokens | null {
  try {
    return JSON.parse(localStorage.getItem(SESSION_KEY) ?? 'null') as Tokens | null
  } catch {
    return null
  }
}

function saveTokens(t: Tokens) {
  localStorage.setItem(SESSION_KEY, JSON.stringify(t))
}

export const hasSession = () => readTokens() !== null

export async function login(): Promise<void> {
  if (!config) return
  const verifier = randomString()
  const state = randomString()
  sessionStorage.setItem(VERIFIER_KEY, verifier)
  sessionStorage.setItem(STATE_KEY, state)
  const query = new URLSearchParams({
    response_type: 'code',
    client_id: config.clientId,
    redirect_uri: redirectUri(),
    scope: 'openid email',
    code_challenge: await challengeFor(verifier),
    code_challenge_method: 'S256',
    state,
  })
  nav.to(`https://${config.domain}/oauth2/authorize?${query}`)
}

async function tokenRequest(form: Record<string, string>): Promise<Record<string, unknown>> {
  const res = await fetch(`https://${config!.domain}/oauth2/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ client_id: config!.clientId, ...form }).toString(),
  })
  if (!res.ok) throw new Error('Sign-in failed.')
  return (await res.json()) as Record<string, unknown>
}

// Called when Cognito sends the browser back with ?code=...
export async function handleCallback(): Promise<void> {
  const params = new URLSearchParams(window.location.search)
  const code = params.get('code')
  const verifier = sessionStorage.getItem(VERIFIER_KEY)
  const expected = sessionStorage.getItem(STATE_KEY)
  sessionStorage.removeItem(VERIFIER_KEY)
  sessionStorage.removeItem(STATE_KEY)
  window.history.replaceState({}, '', window.location.pathname)
  if (!code || !verifier || params.get('state') !== expected) {
    await login()
    return
  }
  const body = await tokenRequest({
    grant_type: 'authorization_code',
    code,
    redirect_uri: redirectUri(),
    code_verifier: verifier,
  })
  saveTokens({
    access_token: String(body.access_token),
    refresh_token: typeof body.refresh_token === 'string' ? body.refresh_token : undefined,
    expires_at: Date.now() / 1000 + Number(body.expires_in ?? 3600),
  })
}

export async function getToken(): Promise<string | null> {
  if (!config) return null
  const tokens = readTokens()
  if (!tokens) {
    await login()
    return null
  }
  if (tokens.expires_at - REFRESH_MARGIN_SECONDS > Date.now() / 1000) return tokens.access_token
  if (tokens.refresh_token) {
    try {
      const body = await tokenRequest({ grant_type: 'refresh_token', refresh_token: tokens.refresh_token })
      saveTokens({
        ...tokens,
        access_token: String(body.access_token),
        expires_at: Date.now() / 1000 + Number(body.expires_in ?? 3600),
      })
      return String(body.access_token)
    } catch {
      /* fall through to a fresh sign-in */
    }
  }
  localStorage.removeItem(SESSION_KEY)
  await login()
  return null
}

export function logout() {
  localStorage.removeItem(SESSION_KEY)
  if (!config) return
  const query = new URLSearchParams({ client_id: config.clientId, logout_uri: redirectUri() })
  nav.to(`https://${config.domain}/logout?${query}`)
}
