import type { ComponentProps } from 'react'
import { Slot } from '@radix-ui/react-slot'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'

const variants = cva('button', {
  variants: {
    variant: { primary: 'button-primary', outline: 'button-outline', ghost: 'button-ghost' },
    size: { default: '', icon: 'button-icon' },
  },
  defaultVariants: { variant: 'primary', size: 'default' },
})

export function Button({ asChild, variant, size, className, ...props }: ComponentProps<'button'> & VariantProps<typeof variants> & { asChild?: boolean }) {
  const Component = asChild ? Slot : 'button'
  return <Component className={cn(variants({ variant, size }), className)} {...props} />
}
