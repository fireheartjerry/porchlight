/**
 * The one place a human types into Porchlight. Everything a group actually
 * receives goes in here — a text, a form, a transcribed voicemail, or a photo of
 * a slip somebody left in the church letterbox.
 */

import clsx from 'clsx'
import { ImageUp, Send, X } from 'lucide-react'
import { useRef, useState, type ClipboardEvent, type DragEvent } from 'react'
import { Button } from '../Button'
import { Card } from '../Card'
import { SOURCE_ORDER, sourceMeta } from '../requests/sources'
import type { Source } from '../../types'

export interface PaperSlip {
  name: string
  /** Raw base64 (no data: prefix) — what `POST /api/inbox` wants. */
  base64: string
  /** Full data URL, for the thumbnail. */
  dataUrl: string
}

interface ComposerProps {
  text: string
  onTextChange: (text: string) => void
  source: Source
  onSourceChange: (source: Source) => void
  contact: string
  onContactChange: (contact: string) => void
  slip: PaperSlip | null
  onSlipChange: (slip: PaperSlip | null) => void
  onSend: () => void
  sending: boolean
}

export function Composer({
  text,
  onTextChange,
  source,
  onSourceChange,
  contact,
  onContactChange,
  slip,
  onSlipChange,
  onSend,
  sending,
}: ComposerProps) {
  const fileInput = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)

  const readFile = (file: File | undefined | null) => {
    if (!file || !file.type.startsWith('image/')) return
    const reader = new FileReader()
    reader.onload = () => {
      const result = typeof reader.result === 'string' ? reader.result : ''
      onSlipChange({ name: file.name || 'paper-slip.jpg', base64: result.split(',')[1] ?? '', dataUrl: result })
      onSourceChange('paper')
    }
    reader.readAsDataURL(file)
  }

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    setDragging(false)
    readFile(event.dataTransfer.files?.[0])
  }

  const onPaste = (event: ClipboardEvent<HTMLTextAreaElement>) => {
    const file = Array.from(event.clipboardData.files)[0]
    if (file) readFile(file)
  }

  const ready = text.trim().length > 0

  return (
    <Card
      className={clsx('px-5 py-5 transition-colors duration-200', dragging && 'border-lamp/45 bg-lamp/[0.05]')}
    >
      <div
        onDragOver={(event) => {
          event.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
      >
        <label className="block">
          <span className="sr-only">The message</span>
          <textarea
            value={text}
            onChange={(event) => onTextChange(event.target.value)}
            onPaste={onPaste}
            rows={7}
            placeholder="Paste a message the group received…"
            className="w-full resize-y rounded-xl border border-white/10 bg-porch-950/50 px-3.5 py-3 font-display text-[0.95rem] leading-relaxed text-cream placeholder:font-sans placeholder:text-[0.9rem] placeholder:text-cream-faint focus:border-lamp/40"
          />
        </label>

        {slip && (
          <div className="mt-3 flex items-center gap-3 rounded-xl border border-white/[0.09] bg-white/[0.03] p-2.5">
            <img
              src={slip.dataUrl}
              alt=""
              className="h-14 w-14 shrink-0 rotate-[-1.5deg] rounded-md border border-white/15 object-cover shadow-lift"
            />
            <div className="min-w-0 flex-1">
              <p className="truncate text-[0.8rem] text-cream">{slip.name}</p>
              <p className="text-[0.72rem] text-cream-faint">
                Sent as an image block — intake reads the handwriting itself.
              </p>
            </div>
            <button
              type="button"
              aria-label="Remove the photo"
              onClick={() => onSlipChange(null)}
              className="rounded-lg border border-white/10 p-1.5 text-cream-faint hover:text-cream"
            >
              <X className="h-3.5 w-3.5" aria-hidden />
            </button>
          </div>
        )}
      </div>

      <div className="mt-3.5 flex flex-wrap items-center gap-x-4 gap-y-3">
        <div>
          <p className="mb-1.5 text-[0.66rem] uppercase tracking-[0.14em] text-cream-faint">How it arrived</p>
          <div role="radiogroup" aria-label="How it arrived" className="flex flex-wrap gap-1">
            {SOURCE_ORDER.map((option) => {
              const meta = sourceMeta(option)
              const Icon = meta.icon
              const active = source === option
              return (
                <button
                  key={option}
                  type="button"
                  role="radio"
                  aria-checked={active}
                  onClick={() => onSourceChange(option)}
                  className={clsx(
                    'inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-[0.76rem] transition-colors duration-150',
                    active
                      ? 'border-lamp/40 bg-lamp/12 text-lamp-glow'
                      : 'border-white/[0.09] bg-white/[0.02] text-cream-faint hover:border-white/20 hover:text-cream',
                  )}
                >
                  <Icon className="h-3.5 w-3.5" aria-hidden />
                  {meta.label}
                </button>
              )
            })}
          </div>
        </div>

        <label className="min-w-[12rem] flex-1">
          <span className="mb-1.5 block text-[0.66rem] uppercase tracking-[0.14em] text-cream-faint">
            From (optional)
          </span>
          <input
            value={contact}
            onChange={(event) => onContactChange(event.target.value)}
            placeholder="phone, email, or a name"
            className="h-9 w-full rounded-lg border border-white/10 bg-porch-950/50 px-2.5 text-[0.82rem] text-cream placeholder:text-cream-faint focus:border-lamp/40"
          />
        </label>

        <div>
          <p className="mb-1.5 text-[0.66rem] uppercase tracking-[0.14em] text-cream-faint">Paper slip</p>
          <input
            ref={fileInput}
            type="file"
            accept="image/*"
            aria-label="Attach a photo of a paper slip"
            className="sr-only"
            onChange={(event) => readFile(event.target.files?.[0])}
          />
          <Button
            size="sm"
            variant="quiet"
            className="h-9 border-white/[0.09] bg-white/[0.02]"
            icon={<ImageUp className="h-3.5 w-3.5" aria-hidden />}
            onClick={() => fileInput.current?.click()}
          >
            Attach a photo
          </Button>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-white/[0.06] pt-3.5">
        <p className="max-w-md text-pretty text-[0.76rem] leading-snug text-cream-faint">
          Porchlight decides on its own. It only wakes you when the policy says it must — danger, money,
          vetting, a concern, or nobody free in time.
        </p>
        <Button
          variant="primary"
          icon={<Send className="h-3.5 w-3.5" aria-hidden />}
          loading={sending}
          disabled={!ready}
          onClick={onSend}
        >
          Send to Porchlight
        </Button>
      </div>
    </Card>
  )
}
