import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { onAuthStateChanged, signInWithPopup, signOut, type User } from 'firebase/auth'
import { auth, googleProvider } from './firebase'
import { api } from './api'
import { browserTimezone } from './dates'
import type { UserSettings } from '../types'

interface AuthState {
  user: User | null
  settings: UserSettings | null
  loading: boolean
  signIn: () => Promise<void>
  logOut: () => Promise<void>
  refreshSettings: () => Promise<void>
  setSettings: (s: UserSettings) => void
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [settings, setSettings] = useState<UserSettings | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    return onAuthStateChanged(auth, async (u) => {
      setUser(u)
      if (u) {
        try {
          let s = await api.me()
          // First visit: adopt the browser's timezone.
          if (s.timezone === 'UTC' && browserTimezone() !== 'UTC') {
            s = await api.updateMe({ timezone: browserTimezone() })
          }
          setSettings(s)
        } catch (e) {
          console.error('Could not load settings (is the backend running?)', e)
        }
      } else {
        setSettings(null)
      }
      setLoading(false)
    })
  }, [])

  const value: AuthState = {
    user,
    settings,
    loading,
    signIn: async () => {
      await signInWithPopup(auth, googleProvider)
    },
    logOut: () => signOut(auth),
    refreshSettings: async () => setSettings(await api.me()),
    setSettings,
  }
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}


export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}
