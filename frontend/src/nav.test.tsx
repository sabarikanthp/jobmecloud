import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { NavProvider, useNav } from './nav.tsx'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

function Probe() {
  const { page, jobId, go, openJob } = useNav()
  return (
    <div id="probe" data-page={page} data-job={jobId ?? ''}>
      <button id="open" onClick={() => openJob(9)} />
      <button id="settings" onClick={() => go('Settings')} />
    </div>
  )
}

let container: HTMLDivElement
let root: Root

async function mount() {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  await act(async () => root.render(<NavProvider><Probe /></NavProvider>))
}

const probe = () => container.querySelector('#probe') as HTMLElement
const shown = () => ({ page: probe().dataset.page, job: probe().dataset.job })

async function changeAddress(hash: string) {
  await act(async () => {
    window.location.hash = hash
    window.dispatchEvent(new HashChangeEvent('hashchange'))
  })
}

beforeEach(() => {
  window.location.hash = ''
})
afterEach(async () => {
  await act(async () => root.unmount())
  container.remove()
})

describe('navigation follows the web address', () => {
  it('starts on Today with no address', async () => {
    await mount()
    expect(shown()).toEqual({ page: 'Today', job: '' })
  })

  it('starts on the job named by the address, as a new tab would', async () => {
    window.location.hash = '#/jobs/7'
    await mount()
    expect(shown()).toEqual({ page: 'Jobs', job: '7' })
  })

  it('follows the address when it changes (the back button, or following a link)', async () => {
    await mount()
    await changeAddress('#/jobs/12')
    expect(shown()).toEqual({ page: 'Jobs', job: '12' })
    await changeAddress('#/follow-ups')
    expect(shown()).toEqual({ page: 'Follow-ups', job: '' })
  })

  it('opening a job puts the job in the address', async () => {
    await mount()
    await act(async () => (container.querySelector('#open') as HTMLButtonElement).click())
    expect(window.location.hash).toBe('#/jobs/9')
    expect(shown()).toEqual({ page: 'Jobs', job: '9' })
  })

  it('going to a page puts the page in the address and leaves the job', async () => {
    window.location.hash = '#/jobs/7'
    await mount()
    await act(async () => (container.querySelector('#settings') as HTMLButtonElement).click())
    expect(window.location.hash).toBe('#/settings')
    expect(shown()).toEqual({ page: 'Settings', job: '' })
  })
})
