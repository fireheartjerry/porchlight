import { useContext } from 'react'
import { ToastContext, type ToastApi } from '../components/toast-context'

/** `useToast().push({ title: 'Resumed. Porchlight is back on it.' })` */
export function useToast(): ToastApi {
  return useContext(ToastContext)
}
