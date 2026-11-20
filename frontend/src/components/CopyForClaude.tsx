import { useState } from 'react'

/** Copies a short reference for pasting into a Claude chat. If the browser blocks the clipboard, the text is shown
 *  selected so it can be copied by hand. */
export default function CopyForClaude({ text }: { text: string }) {
  const [state, setState] = useState<'idle' | 'copied' | 'manual'>('idle')

  async function copy() {
    try {
      await navigator.clipboard.writeText(text)
      setState('copied')
      setTimeout(() => setState('idle'), 2500)
    } catch {
      setState('manual')
    }
  }

  return (
    <span className="copy-for-claude">
      <button type="button" onClick={copy} title="Copy a reference you can paste into a Claude chat">
        Copy for Claude
      </button>
      {state === 'copied' && <span className="saved-note"> Copied</span>}
      {state === 'manual' && (
        <input readOnly value={text} aria-label="Reference to copy" onFocus={(e) => e.currentTarget.select()} size={Math.min(text.length, 60)} />
      )}
    </span>
  )
}
