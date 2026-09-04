import { createContext } from 'react'

export type ToastTone = 'quiet' | 'good' | 'warn' | 'bad'

export interface Toast {
  id: number
  title: string
  description?: string
  tone: ToastTone
}

export interface ToastApi {
  toasts: Toast[]
  push: (toast: Omit<Toast, 'id' | 'tone'> & { tone?: ToastTone }) => number
  dismiss: (id: number) => void
}

export const ToastContext = createContext<ToastApi>({
  toasts: [],
  push: () => 0,
  dismiss: () => {},
})
