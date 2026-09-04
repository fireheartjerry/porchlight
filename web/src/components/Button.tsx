import clsx from 'clsx'
import { Loader2 } from 'lucide-react'
import type { ButtonHTMLAttributes, ReactNode } from 'react'

type Variant = 'primary' | 'ghost' | 'danger' | 'quiet'
type Size = 'sm' | 'md'

const VARIANTS: Record<Variant, string> = {
  primary:
    'bg-lamp text-porch-950 border-lamp/60 shadow-[0_10px_30px_-14px_rgba(245,158,11,0.9)] hover:bg-lamp-glow hover:border-lamp-glow',
  ghost: 'bg-white/[0.04] text-cream border-white/12 hover:bg-white/[0.08] hover:border-white/20',
  danger: 'bg-ember/12 text-ember border-ember/35 hover:bg-ember/20 hover:border-ember/55',
  quiet: 'bg-transparent text-cream-dim border-transparent hover:bg-white/[0.06] hover:text-cream',
}

const SIZES: Record<Size, string> = {
  sm: 'h-8 px-3 text-[0.78rem] gap-1.5 rounded-lg',
  md: 'h-10 px-4 text-[0.85rem] gap-2 rounded-xl',
}

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
  loading?: boolean
  icon?: ReactNode
  block?: boolean
}

export function Button({
  variant = 'ghost',
  size = 'md',
  loading = false,
  icon,
  block,
  className,
  children,
  disabled,
  ...rest
}: ButtonProps) {
  return (
    <button
      type="button"
      {...rest}
      disabled={disabled || loading}
      className={clsx(
        'inline-flex select-none items-center justify-center whitespace-nowrap border font-medium tracking-[-0.005em] transition-[background-color,border-color,color,transform] duration-150 active:translate-y-px disabled:pointer-events-none disabled:opacity-45',
        VARIANTS[variant],
        SIZES[size],
        block && 'w-full',
        className,
      )}
    >
      {loading ? <Loader2 aria-hidden className="h-3.5 w-3.5 animate-spin" /> : icon}
      {children}
    </button>
  )
}

/** Icon-only button. `label` is required — it becomes the accessible name. */
export function IconButton({
  label,
  icon,
  className,
  variant = 'quiet',
  ...rest
}: Omit<ButtonProps, 'children' | 'size'> & { label: string; icon: ReactNode }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      {...rest}
      className={clsx(
        'inline-flex h-8 w-8 items-center justify-center rounded-lg border transition-colors duration-150 disabled:opacity-40',
        VARIANTS[variant],
        className,
      )}
    >
      {icon}
    </button>
  )
}
