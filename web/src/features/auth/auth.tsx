import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { createClient, integer, record, str, type Client } from '@/api/client'

type Session = { username: string, id: bigint, request: Client }
type Auth = { session: Session | null, notice: string, login: (name: string, password: string) => Promise<void>, logout: () => void }
const Context = createContext<Auth | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null)
  const [notice, setNotice] = useState('')
  const active = useRef<AbortController | null>(null)
  useEffect(() => () => active.current?.abort(), [])

  function clear(message = '') {
    active.current?.abort()
    active.current = null
    setSession(null)
    setNotice(message)
  }
  async function login(name: string, password: string) {
    clear()
    const attempt = new AbortController()
    active.current = attempt
    try {
      const anonymous = createClient(null, attempt.signal)
      const token = str(record(await anonymous('/auth/login', { body: { username: name, password } })).access_token)
      let verified = false
      const request = createClient(token, attempt.signal, () => {
        if (verified && active.current === attempt) clear('Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.')
      })
      const user = record(await request('/auth/me'))
      attempt.signal.throwIfAborted()
      const identity = { username: str(user.username), id: integer(user.id), request }
      verified = true
      setSession(identity)
    } catch (error) {
      if (active.current === attempt) clear()
      throw error
    }
  }
  return <Context.Provider value={{ session, notice, login, logout: () => clear() }}>{children}</Context.Provider>
}
export function useAuth() {
  const auth = useContext(Context)
  if (!auth) throw new Error('Thiếu AuthProvider.')
  return auth
}
