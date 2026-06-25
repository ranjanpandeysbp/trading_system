import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Mail } from 'lucide-react'
import { apiErrorMessage, forgotPassword } from '../api/client'
import { AuthLayout } from '../components/layout/AuthLayout'
import { Card } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { FormField, Input } from '../components/ui/Form'
import { Alert } from '../components/ui/Feedback'

export default function ForgotPassword() {
  const [email, setEmail] = useState('')
  const [message, setMessage] = useState('')
  const [debugInfo, setDebugInfo] = useState<{ reset_token?: string; reset_url?: string } | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setMessage('')
    setDebugInfo(null)
    setLoading(true)
    try {
      const res = await forgotPassword(email)
      setMessage(res.message)
      if (res.reset_token) {
        setDebugInfo({ reset_token: res.reset_token, reset_url: res.reset_url })
      }
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <AuthLayout title="Forgot password" subtitle="Enter your registered email to reset your password">
      <Card>
        <form onSubmit={handleSubmit} className="space-y-4">
          <FormField label="Email">
            <Input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              autoComplete="email"
              required
            />
          </FormField>
          {error && <Alert type="error">{error}</Alert>}
          {message && <Alert type="success">{message}</Alert>}
          {debugInfo?.reset_token && (
            <Alert type="success">
              <p className="mb-2 text-xs text-slate-400">Dev mode — use this reset link:</p>
              <Link to={`/reset-password?token=${debugInfo.reset_token}`} className="break-all text-blue-400 hover:underline">
                Reset password
              </Link>
            </Alert>
          )}
          <Button type="submit" disabled={loading} className="w-full">
            <Mail size={16} />
            {loading ? 'Sending...' : 'Send reset link'}
          </Button>
        </form>
        <p className="mt-5 text-center text-sm text-slate-500">
          <Link to="/login" className="text-blue-400 hover:text-blue-300">
            Back to sign in
          </Link>
        </p>
      </Card>
    </AuthLayout>
  )
}
