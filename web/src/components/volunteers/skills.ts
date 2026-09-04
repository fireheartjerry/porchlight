/**
 * Skills come off the roster as tokens (`drive`, `translate:tamil`,
 * `childcare-cleared`). A coordinator reads people, not tokens, so we say them
 * the way a person would.
 */

import {
  Baby,
  Car,
  ChefHat,
  Dumbbell,
  HeartHandshake,
  Languages,
  Laptop,
  Leaf,
  Package,
  ShoppingBasket,
  Sparkles,
  UtensilsCrossed,
  type LucideIcon,
} from 'lucide-react'

const LABELS: Record<string, string> = {
  drive: 'Driving',
  lift: 'Heavy lifting',
  cook: 'Cooking',
  meal: 'Meals',
  groceries: 'Groceries',
  errand: 'Errands',
  chore: 'Yard & chores',
  tech: 'Tech help',
  companionship: 'Company',
  'childcare-cleared': 'Childcare, cleared',
  childcare: 'Childcare',
}

const ICONS: Record<string, LucideIcon> = {
  drive: Car,
  lift: Dumbbell,
  cook: ChefHat,
  meal: UtensilsCrossed,
  groceries: ShoppingBasket,
  errand: Package,
  chore: Leaf,
  tech: Laptop,
  companionship: HeartHandshake,
  'childcare-cleared': Baby,
  childcare: Baby,
}

function titleCase(value: string): string {
  return value
    .split(/[\s_-]+/)
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
}

export function skillLabel(skill: string): string {
  if (skill.startsWith('translate:')) {
    const language = skill.slice('translate:'.length)
    return `Speaks ${titleCase(language)}`
  }
  return LABELS[skill] ?? titleCase(skill)
}

export function skillIcon(skill: string): LucideIcon {
  if (skill.startsWith('translate:')) return Languages
  return ICONS[skill] ?? Sparkles
}

/** Sort so the headline skills lead and language skills trail. */
export function orderSkills(skills: string[]): string[] {
  return [...skills].sort((a, b) => {
    const at = a.startsWith('translate:') ? 1 : 0
    const bt = b.startsWith('translate:') ? 1 : 0
    return at - bt || a.localeCompare(b)
  })
}
