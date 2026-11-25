import { useState, type FormEvent } from 'react'
import { ArrowRight, Eye, EyeOff, LockKeyhole, UserRound } from 'lucide-react'
import { Navigate, useLocation } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card } from '@/components/ui/card'
import { PageHeader } from '@/components/page-header'
import { Engraving } from '@/components/engraving'
import { Brand } from '@/components/brand'
import { useAuth } from './auth'
import { CashFlowIllustration } from './cash-flow-illustration'

export function Login() {
  const { session, login, notice } = useAuth()
  const location = useLocation()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [visible, setVisible] = useState(false)
  if (session) {
    const from = location.state?.from
    const chatPath = typeof from === 'string' && /^\/chat(?:\/[\da-f]{8}(?:-[\da-f]{4}){3}-[\da-f]{12})?$/i.test(from)
    return <Navigate replace to={chatPath ? from : '/dashboard'}/>
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy) return
    const fields = new FormData(event.currentTarget)
    const name = String(fields.get('username') || '').trim()
    if (!name) { setError('Vui lòng nhập tên đăng nhập.'); return }
    setBusy(true)
    setError('')
    try { await login(name, String(fields.get('password'))) }
    catch (e) { setError(e instanceof Error ? e.message : 'Đăng nhập thất bại.') }
    finally { setBusy(false) }
  }
  return <main className="login">
    <aside className="login-intro" aria-label="Giới thiệu MoneyMind AI">
      <Engraving/><div className="login-brand"><Brand/></div>
      <div className="login-story">
        <p className="login-headline">Nhìn rõ dòng tiền<br/><em>mỗi tháng.</em></p>
        <p className="login-description">Theo dõi thu chi, quản lý ngân sách và trao đổi với trợ lý AI về tài chính cá nhân của bạn.</p>
        <CashFlowIllustration/>
      </div>
    </aside>
    <div className="login-workspace"><Card className="login-panel">
    <span className="login-key"><LockKeyhole aria-hidden="true"/></span><PageHeader title="Đăng nhập"/><p className="subtle">Truy cập không gian tài chính của bạn.</p>
    <form onSubmit={submit} aria-busy={busy}>
      <label htmlFor="username">Tên đăng nhập</label><Input leading={<UserRound/>} id="username" name="username" placeholder="Nhập tên đăng nhập" required maxLength={64} autoComplete="username"/>
      <label htmlFor="password">Mật khẩu</label><Input leading={<LockKeyhole/>} id="password" name="password" type={visible ? 'text' : 'password'} placeholder="Nhập mật khẩu" required maxLength={256} autoComplete="current-password"
        trailing={<Button size="icon" variant="ghost" type="button" aria-label={visible ? 'Ẩn mật khẩu' : 'Hiện mật khẩu'} onClick={() => setVisible(!visible)}>{visible ? <EyeOff/> : <Eye/>}</Button>}/>
      {(error || notice) && <p className="error" role="alert">{error || notice}</p>}
      <Button className="login-submit" disabled={busy}>{busy ? 'Đang đăng nhập…' : 'Đăng nhập'}<ArrowRight size={16}/></Button>
    </form></Card></div></main>
}
