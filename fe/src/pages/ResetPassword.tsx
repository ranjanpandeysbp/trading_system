import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { KeyRound } from 'lucide-react'
import { apiErrorMessage, resetPassword } from '../api/client'
import { useAuth } from '../context/AuthContext'
import { AuthLayout } from '../components/layout/AuthLayout'
import { Card } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { FormField, Input } from '../components/ui/Form'
import { Alert } from '../components/ui/Feedback'

export default function ResetPassword() {
  const { setSession } = useAuth()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const tokenFromUrl = searchParams.get('token') ?? ''

  const [token, setToken] = useState(tokenFromUrl)
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    if (password !== confirm) {
      setError('Passwords do not match')
      return
    }
    setLoading(true)
    try {
      const data = await resetPassword(token, password)
      setSession(data.access_token, data.user)
      navigate('/', { replace: true })
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <AuthLayout title="Reset password" subtitle="Choose a new password for your account">
      <Card>
        <form onSubmit={handleSubmit} className="space-y-4">
          <FormField label="Reset token">
            <Input
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder="Paste token from email"
              required
            />
          </FormField>
          <FormField label="New password">
            <Input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Min. 6 characters"
              autoComplete="new-password"
              required
            />
          </FormField>
          <FormField label="Confirm new password">
            <Input
              type="password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              placeholder="Repeat password"
              autoComplete="new-password"
              required
            />
          </FormField>
          {error && <Alert type="error">{error}</Alert>}
          <Button type="submit" disabled={loading} className="w-full">
            <KeyRound size={16} />
            {loading ? 'Updating...' : 'Update password'}
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
