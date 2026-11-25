import { Navigate, Outlet, Route, Routes, useLocation } from 'react-router-dom'
import { lazy, Suspense } from 'react'
import { useAuth } from '@/features/auth/auth'
import { Login } from '@/features/auth/login'
import { AppLayout } from './shell'

const Dashboard = lazy(() => import('@/features/dashboard/dashboard').then(module => ({ default: module.Dashboard })))
const Transactions = lazy(() => import('@/features/transactions/transactions'))
const Budgets = lazy(() => import('@/features/budgets/budgets'))
const Chat = lazy(() => import('@/features/chat/chat'))
const Knowledge = lazy(() => import('@/features/knowledge/knowledge'))

function Protected() {
  const { session } = useAuth()
  const location = useLocation()
  return session ? <Outlet key={session.id.toString()}/> : <Navigate replace to="/login" state={{ from: location.pathname }}/>
}
export function AppRoutes() {
  return <Routes><Route path="/login" element={<Login/>}/><Route element={<Protected/>}><Route element={<AppLayout/>}>
    <Route index element={<Navigate replace to="/dashboard"/>}/>
    <Route path="/dashboard" element={<Suspense fallback={<p role="status" className="panel-state">Đang mở tổng quan…</p>}><Dashboard/></Suspense>}/>
    <Route path="/transactions" element={<Suspense fallback={<p role="status" className="panel-state">Đang mở giao dịch…</p>}><Transactions/></Suspense>}/>
    <Route path="/budgets" element={<Suspense fallback={<p role="status" className="panel-state">Đang mở ngân sách…</p>}><Budgets/></Suspense>}/>
    <Route path="/chat/:conversationId?" element={<Suspense fallback={<p role="status" className="panel-state">Đang mở hội thoại…</p>}><Chat/></Suspense>}/>
    <Route path="/knowledge" element={<Suspense fallback={<p role="status" className="panel-state">Đang mở kho tài liệu…</p>}><Knowledge/></Suspense>}/>
  </Route></Route><Route path="*" element={<Navigate replace to="/dashboard"/>}/></Routes>
}
