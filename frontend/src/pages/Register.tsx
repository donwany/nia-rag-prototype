import { useState, type FormEvent } from 'react'
import { Link, Navigate } from 'react-router-dom'
import { errorMessage } from '../api/client'
import { useAuth } from '../context/AuthContext'

const MIN_PASSWORD_LENGTH = 8

export default function Register() {
  const { user, register } = useAuth()
  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  if (user) return <Navigate to="/" replace />

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault()
    if (password !== confirm) {
      setError('The two passwords do not match')
      return
    }
    setError('')
    setBusy(true)
    try {
      await register(email, password, fullName)
    } catch (err) {
      setError(errorMessage(err, 'Could not create your account'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-dvh items-center justify-center bg-slate-50 px-4 py-8">
      <div className="w-full max-w-sm">
        <div className="mb-6 text-center">
          <span className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-nia-green text-sm font-bold text-white">
            NIA
          </span>
          <h1 className="text-2xl font-semibold text-slate-900">Create an account</h1>
          <p className="mt-1 text-sm text-slate-500">
            Save your questions and come back to them later.
          </p>
        </div>

        <form
          onSubmit={handleSubmit}
          className="space-y-4 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm"
        >
          {error && (
            <p
              role="alert"
              className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700"
            >
              {error}
            </p>
          )}

          <div>
            <label htmlFor="name" className="mb-1 block text-sm font-medium text-slate-700">
              Full name <span className="font-normal text-slate-400">(optional)</span>
            </label>
            <input
              id="name"
              type="text"
              autoComplete="name"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              className="field"
              placeholder="Ama Mensah"
            />
          </div>

          <div>
            <label htmlFor="email" className="mb-1 block text-sm font-medium text-slate-700">
              Email
            </label>
            <input
              id="email"
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="field"
              placeholder="you@example.com"
            />
          </div>

          <div>
            <label htmlFor="password" className="mb-1 block text-sm font-medium text-slate-700">
              Password
            </label>
            <input
              id="password"
              type="password"
              required
              minLength={MIN_PASSWORD_LENGTH}
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="field"
              placeholder="At least 8 characters"
              aria-describedby="password-hint"
            />
            <p id="password-hint" className="mt-1 text-xs text-slate-500">
              Use at least {MIN_PASSWORD_LENGTH} characters.
            </p>
          </div>

          <div>
            <label htmlFor="confirm" className="mb-1 block text-sm font-medium text-slate-700">
              Confirm password
            </label>
            <input
              id="confirm"
              type="password"
              required
              autoComplete="new-password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              className="field"
              placeholder="••••••••"
            />
          </div>

          <button type="submit" className="btn-primary w-full" disabled={busy}>
            {busy ? 'Creating account…' : 'Create account'}
          </button>
        </form>

        <p className="mt-4 text-center text-sm text-slate-600">
          Already registered?{' '}
          <Link to="/login" className="font-medium text-nia-green underline underline-offset-2">
            Sign in
          </Link>
        </p>
      </div>
    </div>
  )
}
