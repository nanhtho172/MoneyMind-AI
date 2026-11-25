import { useEffect, useId, useRef, useState } from 'react'
import { ChevronsUpDown, CircleUserRound, LogOut, X } from 'lucide-react'
import { useAuth } from '@/features/auth/auth'
import { Dialog } from './ui/dialog'
import { Button } from './ui/button'

export function AccountMenu() {
  const { session, logout } = useAuth()
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const first = useRef<HTMLButtonElement>(null)
  const info = useRef<HTMLDialogElement>(null)
  const id = useId()
  useEffect(() => {
    if (!open) return
    first.current?.focus()
    function outside(event: PointerEvent) {
      if (!root.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', outside)
    return () => document.removeEventListener('pointerdown', outside)
  }, [open])
  if (!session) return null
  const initials = Array.from(session.username).slice(0, 2).join('').toLocaleUpperCase('vi')
  return <div ref={root} className="account" onKeyDown={event => {
    if (open && event.key === 'Escape') {
      event.preventDefault()
      event.stopPropagation()
      setOpen(false)
      trigger.current?.focus()
    }
  }} onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false) }}>
    <button className="account-trigger" ref={trigger} type="button" aria-controls={id} aria-expanded={open} onClick={() => setOpen(!open)}>
      <span className="avatar">{initials}</span><span><strong>{session.username}</strong><small>Tài khoản cá nhân</small></span><ChevronsUpDown/>
    </button>
    <div className="account-pop" id={id} hidden={!open}>
      <button ref={first} onClick={() => { setOpen(false); info.current?.showModal() }}><CircleUserRound/>Thông tin tài khoản</button>
      <button onClick={logout}><LogOut/>Đăng xuất</button>
    </div>
    <Dialog label="Thông tin tài khoản" ref={info} className="account-info" onClose={() => trigger.current?.focus()}>
      <header><h2>Thông tin tài khoản</h2><Button size="icon" variant="ghost" aria-label="Đóng thông tin tài khoản" onClick={() => info.current?.close()}><X/></Button></header>
      <div className="account-identity"><span className="avatar">{initials}</span><strong>{session.username}</strong></div>
      <dl><div><dt>Tên đăng nhập</dt><dd>{session.username}</dd></div><div><dt>Mã tài khoản</dt><dd>{String(session.id)}</dd></div></dl>
    </Dialog>
  </div>
}
