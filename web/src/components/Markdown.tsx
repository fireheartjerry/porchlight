import clsx from 'clsx'
import { Fragment, type ReactNode } from 'react'

/**
 * A deliberately tiny Markdown renderer for Decision Card context and the daily
 * brief. Supports paragraphs, `##` headings, `-`/`*` bullets, `**bold**`,
 * `*italic*` and `` `code` ``.
 *
 * It builds React elements — there is no `dangerouslySetInnerHTML` anywhere, so
 * agent-authored text cannot inject markup.
 */

const INLINE = /(\*\*[^*\n]+\*\*|\*[^*\n]+\*|`[^`\n]+`)/g

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const out: ReactNode[] = []
  let index = 0
  let key = 0
  for (const match of text.matchAll(INLINE)) {
    const start = match.index ?? 0
    if (start > index) out.push(text.slice(index, start))
    const token = match[0]
    if (token.startsWith('**')) {
      out.push(
        <strong key={`${keyPrefix}-b${key}`} className="font-semibold text-cream">
          {token.slice(2, -2)}
        </strong>,
      )
    } else if (token.startsWith('`')) {
      out.push(
        <code
          key={`${keyPrefix}-c${key}`}
          className="rounded bg-white/[0.08] px-1 py-0.5 font-mono text-[0.82em] text-lamp-wash"
        >
          {token.slice(1, -1)}
        </code>,
      )
    } else {
      out.push(
        <em key={`${keyPrefix}-i${key}`} className="italic text-cream-dim">
          {token.slice(1, -1)}
        </em>,
      )
    }
    index = start + token.length
    key += 1
  }
  if (index < text.length) out.push(text.slice(index))
  return out
}

function isQuote(block: string): boolean {
  const trimmed = block.trim()
  return trimmed.length > 1 && trimmed.startsWith('"') && trimmed.endsWith('"')
}

export function Markdown({ children, className }: { children: string; className?: string }) {
  const blocks = children.replace(/\r\n/g, '\n').split(/\n{2,}/)

  return (
    <div className={clsx('space-y-3 text-[0.875rem] leading-relaxed text-cream-dim', className)}>
      {blocks.map((block, blockIndex) => {
        const trimmed = block.trim()
        if (!trimmed) return null
        const key = `b${blockIndex}`
        const lines = trimmed.split('\n')

        if (lines.every((line) => /^\s*[-*]\s+/.test(line))) {
          return (
            <ul key={key} className="space-y-1.5 pl-1">
              {lines.map((line, lineIndex) => (
                <li key={`${key}-${lineIndex}`} className="flex gap-2.5">
                  <span aria-hidden className="mt-[0.55em] h-1 w-1 shrink-0 rounded-full bg-lamp/70" />
                  <span>{renderInline(line.replace(/^\s*[-*]\s+/, ''), `${key}-${lineIndex}`)}</span>
                </li>
              ))}
            </ul>
          )
        }

        if (/^#{1,4}\s+/.test(trimmed)) {
          const level = (trimmed.match(/^#+/)?.[0].length ?? 2) as 1 | 2 | 3 | 4
          const text = trimmed.replace(/^#{1,4}\s+/, '')
          const Tag = (['h2', 'h3', 'h4', 'h4'] as const)[level - 1] ?? 'h4'
          return (
            <Tag
              key={key}
              className={clsx('text-cream', level <= 2 ? 'text-lg' : 'text-[0.95rem] font-medium')}
            >
              {renderInline(text, key)}
            </Tag>
          )
        }

        if (isQuote(trimmed)) {
          return (
            <blockquote
              key={key}
              className="border-l-2 border-lamp/40 bg-white/[0.03] py-2 pl-3.5 pr-3 font-display text-[0.95rem] italic leading-relaxed text-cream/90"
            >
              {renderInline(trimmed.slice(1, -1), key)}
            </blockquote>
          )
        }

        return (
          <p key={key} className="text-pretty">
            {lines.map((line, lineIndex) => (
              <Fragment key={`${key}-${lineIndex}`}>
                {lineIndex > 0 && <br />}
                {renderInline(line, `${key}-${lineIndex}`)}
              </Fragment>
            ))}
          </p>
        )
      })}
    </div>
  )
}
