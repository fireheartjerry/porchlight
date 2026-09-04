/** Small formatting helpers. Everything here is pure and timezone-naive-friendly. */

export function relativeTime(value: string | null | undefined, now = Date.now()): string {
  if (!value) return '—'
  const then = new Date(value).getTime()
  if (Number.isNaN(then)) return '—'
  const diff = Math.round((now - then) / 1000)
  const ahead = diff < 0
  const seconds = Math.abs(diff)
  if (seconds < 45) return ahead ? 'in a moment' : 'just now'
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return ahead ? `in ${minutes}m` : `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return ahead ? `in ${hours}h` : `${hours}h ago`
  const days = Math.round(hours / 24)
  if (days < 14) return ahead ? `in ${days}d` : `${days}d ago`
  return new Date(value).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

export function clockTime(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
}

export function preciseTime(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleTimeString(undefined, {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

export function dayLabel(value: string | null | undefined): string {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const today = new Date()
  const sameDay = date.toDateString() === today.toDateString()
  if (sameDay) return 'Today'
  const yesterday = new Date(today.getTime() - 86_400_000)
  if (date.toDateString() === yesterday.toDateString()) return 'Yesterday'
  return date.toLocaleDateString(undefined, { weekday: 'long', month: 'short', day: 'numeric' })
}

export function formatWindow(start: string | null, end: string | null): string {
  if (!start && !end) return 'Whenever suits'
  if (start && !end) return `${dayLabel(start)} from ${clockTime(start)}`
  if (!start && end) return `Before ${clockTime(end)}`
  return `${dayLabel(start)} ${clockTime(start)}–${clockTime(end)}`
}

/** Card-sized window: "Fri 7:30 am" / "Today 2–6 pm" / "Flexible". */
export function formatWindowShort(start: string | null, end: string | null): string {
  if (!start) return end ? `by ${clockTime(end)}` : 'Flexible'
  const date = new Date(start)
  if (Number.isNaN(date.getTime())) return 'Flexible'
  const today = new Date()
  const day =
    date.toDateString() === today.toDateString()
      ? 'Today'
      : date.toLocaleDateString(undefined, { weekday: 'short' })
  return `${day} ${clockTime(start)}`
}

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (!parts.length) return '??'
  if (parts.length === 1) return parts[0]!.slice(0, 2).toUpperCase()
  return `${parts[0]![0]!}${parts[parts.length - 1]![0]!}`.toUpperCase()
}

export function firstName(name: string): string {
  return name.trim().split(/\s+/)[0] ?? name
}

/** "awaiting_reply" → "Awaiting reply" */
export function humanise(value: string): string {
  const spaced = value.replace(/[_-]+/g, ' ').trim()
  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

export function pluralise(count: number, singular: string, plural = `${singular}s`): string {
  return `${count} ${count === 1 ? singular : plural}`
}
