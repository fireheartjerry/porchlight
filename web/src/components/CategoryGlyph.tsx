import { Layers, Package, type LucideIcon } from 'lucide-react'

import { CATEGORY_ICONS } from '../lib/kinds'

const LOOKUP = CATEGORY_ICONS as Record<string, LucideIcon | undefined>

/** Icon for a request category; unknown or missing categories fall back gracefully. */
export function CategoryGlyph({
  category,
  className,
  fallback = 'package',
}: {
  category: string | null | undefined
  className?: string
  fallback?: 'package' | 'layers'
}) {
  const Icon = (category ? LOOKUP[category] : undefined) ?? (fallback === 'layers' ? Layers : Package)
  return <Icon className={className} aria-hidden />
}
