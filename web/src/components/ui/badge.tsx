import type { ReactNode } from 'react'

export function Badge({ tone = 'neutral', children }: { tone?: 'neutral' | 'success' | 'expense' | 'warning' | 'danger', children: ReactNode }) {
  return <span className="badge" data-tone={tone}>{children}</span>
}
