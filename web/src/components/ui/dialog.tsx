import type { ComponentProps } from 'react'
import { cn } from '@/lib/utils'

type DialogProps = Omit<ComponentProps<'dialog'>, 'open' | 'aria-label'> & {
  label: string
  variant?: 'modal' | 'drawer'
}

export function Dialog({ label, variant = 'modal', className, children, ...props }: DialogProps) {
  return <dialog {...props} aria-label={label} className={cn('dialog', variant, className)}
    onClick={event => {
      props.onClick?.(event)
      if (!event.defaultPrevented && event.target === event.currentTarget) event.currentTarget.close()
    }}>
    <div className="dialog-body">{children}</div>
  </dialog>
}
