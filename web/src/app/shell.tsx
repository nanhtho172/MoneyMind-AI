import { Menu, PanelLeft } from 'lucide-react'
import { Outlet, useLocation } from 'react-router-dom'
import { useEffect, useRef } from 'react'
import { Sidebar } from '@/components/sidebar'
import { Button } from '@/components/ui/button'
import { Dialog } from '@/components/ui/dialog'
import { navigation } from './navigation'

export function AppLayout() {
  const menu = useRef<HTMLDialogElement>(null)
  const { pathname } = useLocation()
  const current = navigation.find(item => pathname === item.path || pathname.startsWith(item.path + '/'))
  useEffect(() => {
    const breakpoint = getComputedStyle(document.documentElement).getPropertyValue('--breakpoint-lg').trim()
    const wide = matchMedia('(min-width: ' + breakpoint + ')')
    const close = () => { if (wide.matches) menu.current?.close() }
    wide.addEventListener('change', close)
    return () => wide.removeEventListener('change', close)
  }, [])

  return <div className="shell">
    <a className="skip" href="#main">Đến nội dung chính</a>
    <aside className="sidebar"><Sidebar/></aside>
    <Dialog variant="drawer" ref={menu} label="Điều hướng"><Sidebar close={() => menu.current?.close()}/></Dialog>
    <div className="workspace">
      <header className="topbar">
        <Button className="menu-button" size="icon" variant="ghost" aria-label="Mở menu" aria-haspopup="dialog" onClick={() => menu.current?.showModal()}><Menu/></Button>
        <PanelLeft className="desktop-icon"/><span className="breadcrumb">Không gian cá nhân</span>
        <span className="divider">/</span><strong>{current?.label}</strong>
      </header>
      <main className="page-content" id="main" tabIndex={-1}><Outlet/></main>
    </div>
  </div>
}
