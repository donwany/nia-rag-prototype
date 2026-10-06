import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import SourcesPanel from './SourcesPanel'
import type { Message } from '../types'

export default function ChatMessage({ message }: { message: Message }) {
  const isUser = message.role === 'user'

  return (
    <div
      className={`flex gap-3 ${isUser ? 'justify-end' : 'justify-start'}`}
      role="listitem"
    >
      {!isUser && (
        <div
          aria-hidden="true"
          className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-nia-green text-sm font-bold text-white"
        >
          NIA
        </div>
      )}

      <div
        className={`max-w-[min(42rem,85%)] rounded-2xl px-4 py-3 ${
          isUser
            ? 'bg-nia-green text-white'
            : 'border border-slate-200 bg-white text-slate-800 shadow-sm'
        }`}
      >
        {isUser ? (
          <p className="whitespace-pre-wrap leading-relaxed">{message.content}</p>
        ) : (
          <>
            <div className="answer">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {message.content}
              </ReactMarkdown>
              {message.streaming && (
                <span className="cursor-blink ml-0.5 inline-block">▍</span>
              )}
            </div>
            {!message.streaming && <SourcesPanel sources={message.sources} />}
          </>
        )}
      </div>
    </div>
  )
}
