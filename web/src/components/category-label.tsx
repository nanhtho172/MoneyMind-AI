import { CarFront, House, Shapes, ShoppingBag, Utensils, Wallet } from 'lucide-react'

const appearances = {
  'Ăn uống': [Utensils, 'gold'], 'Nhà ở': [House, 'mint'], 'Đi lại': [CarFront, 'blue'],
  'Mua sắm': [ShoppingBag, 'coral'], 'Lương': [Wallet, 'mint'], 'Thu nhập khác': [Wallet, 'blue'],
} as const

export function CategoryLabel({ name }: { name: string }) {
  const [Icon, tone] = appearances[name as keyof typeof appearances] ?? [Shapes, 'mint']
  return <span className="category-label"><span className="category-glyph" data-tone={tone}><Icon aria-hidden="true"/></span>{name}</span>
}
