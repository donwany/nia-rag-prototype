import type { ChatSummary } from '../types'
import { useAuth } from '../context/AuthContext'

interface Props {
  chats: ChatSummary[]
  activeChatId: string | null
  open: boolean
  onClose: () => void
  onSelect: (chatId: string) => void
  onNew: () => void
  onDelete: (chatId: string) => void
}

export default function Sidebar({
  chats,
  activeChatId,
  open,
  onClose,
  onSelect,
  onNew,
  onDelete,
}: Props) {
  const { user, logout } = useAuth()

  return (
    <>
      {/* Scrim: only rendered on small screens, where the sidebar overlays. */}
      {open && (
        <div
          className="fixed inset-0 z-20 bg-slate-900/40 md:hidden"
          onClick={onClose}
          aria-hidden="true"
        />
      )}

      <aside
        aria-label="Conversation history"
        className={`fixed inset-y-0 left-0 z-30 flex w-72 flex-col border-r border-slate-200 bg-white
                    transition-transform md:static md:translate-x-0
                    ${open ? 'translate-x-0' : '-translate-x-full'}`}
      >
        <div className="flex items-center justify-between border-b border-slate-200 p-4">
          <div className="flex items-center gap-2">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-nia-green text-xs font-bold text-white">
              NIA
            </span>
            <span className="font-semibold text-slate-900">Assistant</span>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1 text-slate-500 hover:bg-slate-100 md:hidden"
            aria-label="Close sidebar"
          >
            <svg viewBox="0 0 20 20" fill="currentColor" className="h-5 w-5">
              <path d="M6 6l8 8M14 6l-8 8" stroke="currentColor" strokeWidth="2" />
            </svg>
          </button>
        </div>

        <div className="p-3">
          <button type="button" onClick={onNew} className="btn-primary w-full">
            New conversation
          </button>
        </div>

        <nav className="flex-1 overflow-y-auto px-2 pb-2">
          {chats.length === 0 ? (
            <p className="px-2 py-4 text-sm text-slate-500">
              No conversations yet. Ask a question to get started.
            </p>
          ) : (
            <ul className="space-y-1">
              {chats.map((chat) => (
                <li key={chat.id} className="group relative">
                  <button
                    type="button"
                    onClick={() => onSelect(chat.id)}
                    aria-current={chat.id === activeChatId ? 'true' : undefined}
                    className={`w-full truncate rounded-lg py-2 pl-3 pr-9 text-left text-sm transition ${
                      chat.id === activeChatId
                        ? 'bg-emerald-50 font-medium text-nia-green'
                        : 'text-slate-700 hover:bg-slate-100'
                    }`}
                  >
                    {chat.title}
                  </button>
                  <button
                    type="button"
                    onClick={() => onDelete(chat.id)}
                    aria-label={`Delete conversation: ${chat.title}`}
                    className="absolute right-1 top-1/2 -translate-y-1/2 rounded p-1.5 text-slate-400
                               opacity-0 transition hover:bg-slate-200 hover:text-nia-red
                               focus:opacity-100 group-hover:opacity-100"
                  >
                    <svg viewBox="0 0 20 20" fill="currentColor" className="h-4 w-4">
                      <path d="M7 2h6v2h4v2H3V4h4V2zm-2 6h10l-1 10H6L5 8z" />
                    </svg>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </nav>

        <div className="border-t border-slate-200 p-3">
          <p className="truncate text-sm font-medium text-slate-900">
            {user?.full_name || user?.email}
          </p>
          <button
            type="button"
            onClick={logout}
            className="mt-1 text-sm text-slate-500 hover:text-nia-red"
          >
            Sign out
          </button>
        </div>
      </aside>
    </>
  )
}
