import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'
import App from './App.tsx'
import { authEnabled, handleCallback, hasSession, loadConfig, login } from './auth.ts'

async function start() {
  await loadConfig()
  if (authEnabled()) {
    if (new URLSearchParams(window.location.search).has('code')) await handleCallback()
    if (!hasSession()) {
      await login()
      return // the browser is on its way to the sign-in screen
    }
  }
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
}

void start()
