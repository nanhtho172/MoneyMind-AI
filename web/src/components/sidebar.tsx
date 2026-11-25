import { ArrowUpRight, Sparkles, X } from 'lucide-react'
import { Link, NavLink } from 'react-router-dom'
import { navigation } from '@/app/navigation'
import { AccountMenu } from './account-menu'
import { Engraving } from './engraving'
import { Brand } from './brand'
import { Button } from './ui/button'

export function Sidebar({ close }: { close?: () => void }) {
  return <>
    <div className="side-brand"><Brand/>
      {close && <Button size="icon" variant="ghost" aria-label="Đóng menu" onClick={close}><X/></Button>}
    </div>
    <div className="nav-label">Không gian làm việc</div>
    <nav className="side-nav" aria-label="Điều hướng chính">
      {navigation.map(({ path, label, icon: Icon, enabled }) => enabled
        ? <NavLink key={path} to={path} onClick={close} className={({ isActive }) => isActive ? 'nav-item nav-active' : 'nav-item'}><Icon/>{label}</NavLink>
        : <span key={path} aria-disabled="true" title="Chưa khả dụng" className="nav-item nav-pending"><Icon/>{label}</span>)}
    </nav>
    <div className="sidebar-foot"><div className="assistant-tile"><Engraving/><Sparkles aria-hidden="true"/>
      <strong>Trợ lý tài chính AI</strong><p>Tra cứu dòng tiền và ghi giao dịch qua hội thoại.</p>
      <Link to="/chat" onClick={close}>Hỏi trợ lý <ArrowUpRight/></Link>
    </div><AccountMenu/></div>
  </>
}
