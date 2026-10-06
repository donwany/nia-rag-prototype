export interface User {
  id: string
  email: string
  full_name: string | null
  created_at: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
  expires_in: number
  user: User
}

export interface Source {
  index: number
  title: string
  url: string
  section: string
  content_type: string
  score: number
  snippet: string
}

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  sources: Source[]
  created_at: string
  /** True while tokens are still arriving for this message. */
  streaming?: boolean
}

export interface ChatSummary {
  id: string
  title: string
  message_count: number
  created_at: string
  updated_at: string
}

export interface ChatDetail extends ChatSummary {
  messages: Message[]
}

/** Server-sent events emitted by POST /api/chat/stream. */
export type StreamEvent =
  | { type: 'start'; chat_id: string }
  | { type: 'status'; node: string }
  | { type: 'token'; value: string }
  | {
      type: 'done'
      chat_id: string
      answer: string
      sources: Source[]
      grounded: boolean
    }
  | { type: 'error'; detail: string }
