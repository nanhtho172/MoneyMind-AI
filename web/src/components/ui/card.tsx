import type { ComponentProps, ReactNode } from 'react'
import { cn } from '@/lib/utils'

export function Card({ className, ...props }: ComponentProps<'section'>) {
  return <section className={cn('card', className)} {...props}/>
}

export function CardHeader({ icon, children }: { icon?: ReactNode, children: ReactNode }) {
  return <header className="panel-heading">{icon}<h2>{children}</h2></header>
}
