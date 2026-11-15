import { useId, useState } from 'react'

export default function Tip({ text }: { text: string }) {
  const id = useId()
  const [pinned, setPinned] = useState(false)
  const [hover, setHover] = useState(false)
  const [focus, setFocus] = useState(false)
  const show = pinned || hover || focus
  return (
    <span className="tip" onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}
      onKeyDown={(e) => {
        if (e.key === 'Escape') {
          setPinned(false)
          setHover(false)
          setFocus(false)
        }
      }}
    >
      <button
        type="button"
        className="tip-button"
        aria-label="More about this"
        aria-describedby={id}
        onClick={() => setPinned((p) => !p)}
        onFocus={() => setFocus(true)}
        onBlur={() => setFocus(false)}
      >
        ?
      </button>
      <span id={id} role="tooltip" className="tip-bubble" hidden={!show}>
        {text}
      </span>
    </span>
  )
}
