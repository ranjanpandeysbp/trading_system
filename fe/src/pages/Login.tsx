import { useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { LogIn } from 'lucide-react'
import { apiErrorMessage } from '../api/client'
import { useAuth } from '../context/AuthContext'
import { AuthLayout } from '../components/layout/AuthLayout'
import { Card } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { FormField, Input } from '../components/ui/Form'
import { Alert } from '../components/ui/Feedback'

export default function Login() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const from = (location.state as { from?: string })?.from ?? '/'

  const [identifier, setIdentifier] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await login(identifier, password)
      navigate(from, { replace: true })
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <AuthLayout title="Welcome back" subtitle="Sign in with your email or mobile number">
      <Card>
        <form onSubmit={handleSubmit} className="space-y-4">
          <FormField label="Email or mobile">
            <Input
              value={identifier}
              onChange={(e) => setIdentifier(e.target.value)}
              placeholder="you@example.com or 9876543210"
              autoComplete="username"
              required
            />
          </FormField>
          <FormField label="Password">
            <Input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              autoComplete="current-password"
              required
            />
          </FormField>
          <div className="flex justify-end">
            <Link to="/forgot-password" className="text-sm text-blue-400 hover:text-blue-300">
              Forgot password?
            </Link>
          </div>
          {error && <Alert type="error">{error}</Alert>}
          <Button type="submit" disabled={loading} className="w-full">
            <LogIn size={16} />
            {loading ? 'Signing in...' : 'Sign in'}
          </Button>
        </form>
        <p className="mt-5 text-center text-sm text-slate-500">
          No account?{' '}
          <Link to="/register" className="text-blue-400 hover:text-blue-300">
            Create one
          </Link>
        </p>
      </Card>
    </AuthLayout>
  )
}
