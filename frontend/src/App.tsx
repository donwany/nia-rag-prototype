import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider, useAuth } from './context/AuthContext'
import Chat from './pages/Chat'
import Login from './pages/Login'
import Register from './pages/Register'
import type { ReactNode } from 'react'

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()

  // Hold the route until the stored token has been checked, otherwise a
  // refresh bounces an authenticated user to the login page.
  if (loading) {
    return (
      <div className="flex min-h-dvh items-center justify-center" role="status">
        <span className="sr-only">Loading</span>
        <svg className="h-8 w-8 animate-spin text-nia-green" viewBox="0 0 24 24" aria-hidden="true">
          <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" fill="none" opacity="0.25" />
          <path d="M12 2a10 10 0 0 1 10 10" stroke="currentColor" strokeWidth="3" fill="none" strokeLinecap="round" />
        </svg>
      </div>
    )
  }

  return user ? <>{children}</> : <Navigate to="/login" replace />
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route
            path="/"
            element={
              <RequireAuth>
                <Chat />
              </RequireAuth>
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  )
}
