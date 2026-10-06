import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { authApi, setUnauthorizedHandler, tokenStore } from '../api/client'
import type { User } from '../types'

interface AuthContextValue {
  user: User | null
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  register: (email: string, password: string, fullName?: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  const logout = useCallback(() => {
    tokenStore.clear()
    setUser(null)
  }, [])

  // Restore the session on first load: a stored token is only trustworthy if
  // the server still accepts it.
  useEffect(() => {
    setUnauthorizedHandler(() => setUser(null))

    if (!tokenStore.get()) {
      setLoading(false)
      return
    }
    authApi
      .me()
      .then(setUser)
      .catch(() => tokenStore.clear())
      .finally(() => setLoading(false))
  }, [])

  const login = useCallback(async (email: string, password: string) => {
    const data = await authApi.login(email, password)
    tokenStore.set(data.access_token)
    setUser(data.user)
  }, [])

  const register = useCallback(
    async (email: string, password: string, fullName?: string) => {
      const data = await authApi.register(email, password, fullName)
      tokenStore.set(data.access_token)
      setUser(data.user)
    },
    [],
  )

  const value = useMemo(
    () => ({ user, loading, login, register, logout }),
    [user, loading, login, register, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used inside an AuthProvider')
  }
  return context
}
