import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  fetchMe,
  loginUser,
  logoutUser,
  registerUser,
  setAuthToken,
  type UserInfo,
} from '../api/client'

const TOKEN_KEY = 'ist_auth_token'

type AuthContextValue = {
  user: UserInfo | null
  isLoading: boolean
  isAuthenticated: boolean
  login: (identifier: string, password: string) => Promise<void>
  register: (name: string, mobile: string, email: string, password: string) => Promise<void>
  logout: () => Promise<void>
  setSession: (token: string, user: UserInfo) => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserInfo | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  const setSession = useCallback((token: string, userInfo: UserInfo) => {
    localStorage.setItem(TOKEN_KEY, token)
    setAuthToken(token)
    setUser(userInfo)
  }, [])

  const clearSession = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY)
    setAuthToken(null)
    setUser(null)
  }, [])

  const restoreSession = useCallback(async () => {
    const token = localStorage.getItem(TOKEN_KEY)
    if (!token) {
      setIsLoading(false)
      return
    }
    setAuthToken(token)
    try {
      const me = await fetchMe()
      setUser(me)
    } catch {
      clearSession()
    } finally {
      setIsLoading(false)
    }
  }, [clearSession])

  useEffect(() => {
    restoreSession()
  }, [restoreSession])

  const login = useCallback(async (identifier: string, password: string) => {
    const data = await loginUser({ identifier, password })
    setSession(data.access_token, data.user)
  }, [setSession])

  const register = useCallback(async (name: string, mobile: string, email: string, password: string) => {
    const data = await registerUser({ name, mobile, email, password })
    setSession(data.access_token, data.user)
  }, [setSession])

  const logout = useCallback(async () => {
    try {
      await logoutUser()
    } catch {
      // ignore — clear local session regardless
    }
    clearSession()
  }, [clearSession])

  const value = useMemo(
    () => ({
      user,
      isLoading,
      isAuthenticated: !!user,
      login,
      register,
      logout,
      setSession,
    }),
    [user, isLoading, login, register, logout, setSession],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}

export function getStoredToken() {
  return localStorage.getItem(TOKEN_KEY)
}
