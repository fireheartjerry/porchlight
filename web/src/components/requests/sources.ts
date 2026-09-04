/**
 * How a request arrived. Each channel gets its own glyph and a line of plain
 * English, because "voicemail" and "photo of a paper slip" are very different
 * things to a coordinator and the UI should say so.
 */

import { FileText, Mail, MessageSquare, Phone, ScanLine, Terminal, type LucideIcon } from 'lucide-react'
import type { Source } from '../../types'

export interface SourceMeta {
  label: string
  /** Used in the drawer: "as it arrived, by text message". */
  arrival: string
  icon: LucideIcon
}

export const SOURCE_META: Record<Source, SourceMeta> = {
  form: { label: 'Form', arrival: 'through the request form', icon: FileText },
  sms: { label: 'Text', arrival: 'by text message', icon: MessageSquare },
  email: { label: 'Email', arrival: 'by email', icon: Mail },
  voicemail: { label: 'Voicemail', arrival: 'as a voicemail, transcribed', icon: Phone },
  paper: { label: 'Paper slip', arrival: 'as a photo of a paper slip', icon: ScanLine },
  api: { label: 'API', arrival: 'from a connected system', icon: Terminal },
}

export function sourceMeta(source: Source): SourceMeta {
  return SOURCE_META[source] ?? SOURCE_META.form
}

export const SOURCE_ORDER: Source[] = ['form', 'sms', 'email', 'voicemail', 'paper']
