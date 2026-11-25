import type { ComponentProps, ReactNode } from 'react'
import { cn } from '@/lib/utils'

type InputProps = ComponentProps<'input'> & { leading?: ReactNode, trailing?: ReactNode }

export function Input({ leading, trailing, className, ...props }: InputProps) {
  return <div className="input-wrap">
    {leading}
    <input className={cn('input', className)} {...props}/>
    {trailing}
  </div>
}

export function Select({ className, ...props }: ComponentProps<'select'>) {
  return <select className={cn('native-control', className)} {...props}/>
}

export function Textarea({ className, ...props }: ComponentProps<'textarea'>) {
  return <textarea className={cn('native-control', className)} {...props}/>
}
