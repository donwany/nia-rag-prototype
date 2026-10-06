import { useCallback, useEffect, useRef, useState } from 'react'
import ChatInput from '../components/ChatInput'
import ChatMessage from '../components/ChatMessage'
import Sidebar from '../components/Sidebar'
import { errorMessage, historyApi, streamChat } from '../api/client'
import type { ChatSummary, Message } from '../types'

const NODE_STATUS: Record<string, string> = {
  condense: 'Understanding your question…',
  retrieve: 'Searching the NIA website…',
  grade: 'Checking which pages are relevant…',
  rewrite: 'Refining the search…',
  generate: 'Writing the answer…',
  fallback: 'No matching page found…',
}

const SUGGESTIONS = [
  'How much does it cost to replace a Ghana Card?',
  'Where is the NIA office in Ablekuma Central?',
  'What documents do I need to register for the Ghana Card?',
  'How do I update my personal information?',
]

const newId = () =>
  globalThis.crypto?.randomUUID?.() ?? `tmp-${Date.now()}-${Math.random()}`

export default function Chat() {
  const [messages, setMessages] = useState<Message[]>([])
  const [chats, setChats] = useState<ChatSummary[]>([])
  const [activeChatId, setActiveChatId] = useState<string | null>(null)
  const [sending, setSending] = useState(false)
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')
  const [sidebarOpen, setSidebarOpen] = useState(false)

  const bottomRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  const refreshChats = useCallback(() => {
    historyApi.list().then(setChats).catch(() => undefined)
  }, [])

  useEffect(refreshChats, [refreshChats])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, status])

  // Abandon an in-flight stream if the component goes away.
  useEffect(() => () => abortRef.current?.abort(), [])

  const startNewChat = () => {
    abortRef.current?.abort()
    setMessages([])
    setActiveChatId(null)
    setError('')
    setSidebarOpen(false)
  }

  const openChat = async (chatId: string) => {
    abortRef.current?.abort()
    setSidebarOpen(false)
    setError('')
    try {
      const detail = await historyApi.get(chatId)
      setMessages(detail.messages)
      setActiveChatId(detail.id)
    } catch (err) {
      setError(errorMessage(err, 'Could not open that conversation'))
    }
  }

  const removeChat = async (chatId: string) => {
    try {
      await historyApi.remove(chatId)
      setChats((current) => current.filter((c) => c.id !== chatId))
      if (chatId === activeChatId) startNewChat()
    } catch (err) {
      setError(errorMessage(err, 'Could not delete that conversation'))
    }
  }

  const handleSend = async (question: string) => {
    setError('')
    setSending(true)
    setStatus(NODE_STATUS.condense)

    const assistantId = newId()
    setMessages((current) => [
      ...current,
      {
        id: newId(),
        role: 'user',
        content: question,
        sources: [],
        created_at: new Date().toISOString(),
      },
      {
        id: assistantId,
        role: 'assistant',
        content: '',
        sources: [],
        created_at: new Date().toISOString(),
        streaming: true,
      },
    ])

    const controller = new AbortController()
    abortRef.current = controller
    let chatId = activeChatId

    const update = (patch: Partial<Message>) =>
      setMessages((current) =>
        current.map((m) => (m.id === assistantId ? { ...m, ...patch } : m)),
      )

    try {
      await streamChat(
        question,
        activeChatId,
        (event) => {
          switch (event.type) {
            case 'start':
              chatId = event.chat_id
              setActiveChatId(event.chat_id)
              break
            case 'status':
              setStatus(NODE_STATUS[event.node] ?? '')
              break
            case 'token':
              setStatus('')
              setMessages((current) =>
                current.map((m) =>
                  m.id === assistantId ? { ...m, content: m.content + event.value } : m,
                ),
              )
              break
            case 'done':
              update({
                content: event.answer,
                sources: event.sources,
                streaming: false,
              })
              break
            case 'error':
              setError(event.detail)
              update({ streaming: false })
              break
          }
        },
        controller.signal,
      )
    } catch (err) {
      if (!controller.signal.aborted) {
        setError(errorMessage(err, 'The assistant could not answer that'))
        update({ streaming: false })
      }
    } finally {
      setSending(false)
      setStatus('')
      abortRef.current = null
      update({ streaming: false })
      if (chatId) refreshChats()
    }
  }

  const isEmpty = messages.length === 0

  return (
    <div className="flex h-dvh overflow-hidden bg-slate-50">
      <Sidebar
        chats={chats}
        activeChatId={activeChatId}
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        onSelect={openChat}
        onNew={startNewChat}
        onDelete={removeChat}
      />

      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 border-b border-slate-200 bg-white px-4 py-3">
          <button
            type="button"
            onClick={() => setSidebarOpen(true)}
            className="rounded-lg p-1.5 text-slate-600 hover:bg-slate-100 md:hidden"
            aria-label="Open conversation history"
          >
            <svg viewBox="0 0 20 20" fill="currentColor" className="h-5 w-5">
              <path d="M3 5h14M3 10h14M3 15h14" stroke="currentColor" strokeWidth="2" />
            </svg>
          </button>
          <div className="min-w-0">
            <h1 className="truncate font-semibold text-slate-900">
              National Identification Authority Assistant
            </h1>
            <p className="truncate text-xs text-slate-500">
              Answers grounded in nia.gov.gh
            </p>
          </div>
        </header>

        <div
          className="flex-1 overflow-y-auto px-4 py-6"
          role="list"
          aria-live="polite"
          aria-busy={sending}
        >
          <div className="mx-auto max-w-3xl space-y-4">
            {isEmpty ? (
              <div className="pt-10 text-center">
                <h2 className="text-xl font-semibold text-slate-900">
                  How can I help?
                </h2>
                <p className="mx-auto mt-2 max-w-md text-sm text-slate-500">
                  Ask about the Ghana Card, registration, fees, required documents or
                  where to find your nearest NIA office.
                </p>
                <div className="mx-auto mt-6 grid max-w-xl gap-2 sm:grid-cols-2">
                  {SUGGESTIONS.map((suggestion) => (
                    <button
                      key={suggestion}
                      type="button"
                      onClick={() => handleSend(suggestion)}
                      className="rounded-xl border border-slate-200 bg-white p-3 text-left text-sm
                                 text-slate-700 transition hover:border-nia-green hover:text-nia-green"
                    >
                      {suggestion}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              messages.map((message) => (
                <ChatMessage key={message.id} message={message} />
              ))
            )}

            {status && (
              <p className="pl-11 text-sm italic text-slate-500">{status}</p>
            )}
            {error && (
              <p
                role="alert"
                className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700"
              >
                {error}
              </p>
            )}
            <div ref={bottomRef} />
          </div>
        </div>

        <div className="border-t border-slate-200 bg-white px-4 py-3">
          <div className="mx-auto max-w-3xl">
            <ChatInput onSend={handleSend} disabled={sending} />
            <p className="mt-2 text-center text-xs text-slate-400">
              Information is drawn from nia.gov.gh and may be out of date. Always
              confirm official details with the NIA.
            </p>
          </div>
        </div>
      </main>
    </div>
  )
}
