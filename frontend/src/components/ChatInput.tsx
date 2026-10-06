import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'

interface Props {
  onSend: (question: string) => void
  disabled: boolean
}

const MAX_HEIGHT_PX = 160

export default function ChatInput({ onSend, disabled }: Props) {
  const [value, setValue] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // Grow with the content, up to a cap, instead of scrolling a one-line box.
  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT_PX)}px`
  }, [value])

  const submit = () => {
    const question = value.trim()
    if (!question || disabled) return
    onSend(question)
    setValue('')
  }

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault()
    submit()
  }

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      submit()
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex items-end gap-2">
      <label htmlFor="question" className="sr-only">
        Ask a question about the NIA or the Ghana Card
      </label>
      <textarea
        id="question"
        ref={textareaRef}
        rows={1}
        value={value}
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Ask about the Ghana Card, fees, registration or office locations…"
        className="field resize-none"
        disabled={disabled}
      />
      <button
        type="submit"
        className="btn-primary h-[42px] px-4"
        disabled={disabled || !value.trim()}
        aria-label="Send question"
      >
        {disabled ? (
          <svg className="h-5 w-5 animate-spin" viewBox="0 0 24 24" aria-hidden="true">
            <circle
              cx="12"
              cy="12"
              r="10"
              stroke="currentColor"
              strokeWidth="3"
              fill="none"
              opacity="0.25"
            />
            <path
              d="M12 2a10 10 0 0 1 10 10"
              stroke="currentColor"
              strokeWidth="3"
              fill="none"
              strokeLinecap="round"
            />
          </svg>
        ) : (
          <svg viewBox="0 0 20 20" fill="currentColor" aria-hidden="true" className="h-5 w-5">
            <path d="M2 10 18 2l-5 8 5 8L2 10z" />
          </svg>
        )}
      </button>
    </form>
  )
}
