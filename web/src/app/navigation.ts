import { LayoutDashboard, LibraryBig, MessagesSquare, PieChart, Wallet } from 'lucide-react'

export const navigation = [
  { path: '/dashboard', label: 'Tổng quan', icon: LayoutDashboard, enabled: true },
  { path: '/chat', label: 'Chat AI', icon: MessagesSquare, enabled: true },
  { path: '/transactions', label: 'Giao dịch', icon: Wallet, enabled: true },
  { path: '/budgets', label: 'Ngân sách', icon: PieChart, enabled: true },
  { path: '/knowledge', label: 'Kho tài liệu', icon: LibraryBig, enabled: true },
] as const
