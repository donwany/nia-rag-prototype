import axios, { AxiosError } from 'axios'
import type {
  ChatDetail,
  ChatSummary,
  StreamEvent,
  TokenResponse,
  User,
} from '../types'

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api'
const TOKEN_KEY = 'nia_access_token'

export const tokenStore = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (token: string) => localStorage.setItem(TOKEN_KEY, token),
  clear: () => localStorage.removeItem(TOKEN_KEY),
}

export const api = axios.create({ baseURL: BASE_URL })

api.interceptors.request.use((config) => {
  const token = tokenStore.get()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

/** Callback invoked when the server rejects our token, so the app can log out. */
let onUnauthorized: (() => void) | null = null
export const setUnauthorizedHandler = (handler: () => void) => {
  onUnauthorized = handler
}

api.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    if (error.response?.status === 401) {
      tokenStore.clear()
      onUnauthorized?.()
    }
    return Promise.reject(error)
  },
)

/** Pull a readable message out of a FastAPI error response. */
export const errorMessage = (error: unknown, fallback = 'Something went wrong'): string => {
  if (axios.isAxiosError(error)) {
    const detail = (error.response?.data as { detail?: unknown } | undefined)?.detail
    if (typeof detail === 'string') return detail
    if (error.code === 'ERR_NETWORK') return 'Cannot reach the server. Is the backend running?'
    return error.message || fallback
  }
  if (error instanceof Error) return error.message
  return fallback
}

// -- Auth -------------------------------------------------------------------

export const authApi = {
  register: (email: string, password: string, fullName?: string) =>
    api
      .post<TokenResponse>('/auth/register', {
        email,
        password,
        full_name: fullName || null,
      })
      .then((r) => r.data),

  login: (email: string, password: string) =>
    api.post<TokenResponse>('/auth/login', { email, password }).then((r) => r.data),

  me: () => api.get<User>('/auth/me').then((r) => r.data),
}

// -- History ----------------------------------------------------------------

export const historyApi = {
  list: () => api.get<ChatSummary[]>('/chats').then((r) => r.data),
  get: (chatId: string) => api.get<ChatDetail>(`/chats/${chatId}`).then((r) => r.data),
  remove: (chatId: string) => api.delete(`/chats/${chatId}`).then(() => undefined),
}

// -- Chat -------------------------------------------------------------------

/**
 * Stream an answer over SSE.
 *
 * EventSource only speaks GET and cannot send an Authorization header, so the
 * stream is read manually from a fetch POST instead.
 */
export async function streamChat(
  question: string,
  chatId: string | null,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`${BASE_URL}/chat/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${tokenStore.get() ?? ''}`,
    },
    body: JSON.stringify({ question, chat_id: chatId }),
    signal,
  })

  if (response.status === 401) {
    tokenStore.clear()
    onUnauthorized?.()
    throw new Error('Your session has expired. Please sign in again.')
  }
  if (!response.ok || !response.body) {
    const detail = await response.text().catch(() => '')
    throw new Error(detail || `Request failed with status ${response.status}`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })

    // SSE frames are separated by a blank line; keep the trailing partial.
    const frames = buffer.split('\n\n')
    buffer = frames.pop() ?? ''

    for (const frame of frames) {
      const line = frame.split('\n').find((l) => l.startsWith('data:'))
      if (!line) continue
      try {
        onEvent(JSON.parse(line.slice(5).trim()) as StreamEvent)
      } catch {
        // A malformed frame shouldn't tear down the whole stream.
      }
    }
  }
}
