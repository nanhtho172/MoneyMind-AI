import type { ReactNode } from 'react'

export function PageHeader({ title, description, children }: { title: string, description?: string, children?: ReactNode }) {
  return <header className="page-heading"><div><h1>{title}</h1>{description && <p className="page-description">{description}</p>}</div>{children}</header>
}
