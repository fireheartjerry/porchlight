/**
 * "Run a Tuesday", driven from the browser.
 *
 * It used to be one `POST /api/demo/run_day` that kicked off a FastAPI background task. That
 * works on a long-lived uvicorn and not at all on Lambda: the invocation is frozen the moment
 * the 202 is written, so the task ran a few milliseconds a request and the porch never filled
 * in. The browser is the one process here that genuinely outlives a request, so it does the
 * looping: one `POST /api/inbox` per sample, in order, waiting for each outcome before the
 * next goes out — the same sequencing the server did, minus the part that could not survive.
 *
 * Progress is therefore first-hand rather than inferred from `demo_progress` events, and a
 * request that fails (a gateway timeout on a long graph run) is counted and stepped over
 * instead of stranding the bar.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { postInbox } from '../api'
import { demoSequence } from '../lib/demoSequence'
import type { DemoProgress, RunOutcome, Sample } from '../types'

export interface DayRunState extends DemoProgress {
  /** True while requests are still going out. */
  running: boolean
  /** Set when the run was stopped by hand rather than finishing. */
  stopped: boolean
}

export interface DayRun {
  /** Null until a run starts, then kept on screen so the result stays readable. */
  progress: DayRunState | null
  running: boolean
  start: (samples: Sample[], count: number) => void
  stop: () => void
  clear: () => void
}

export interface DayRunOptions {
  /** Called with every finished outcome, in order — the Inbox logs them in its result panel. */
  onOutcome?: (sample: Sample, outcome: RunOutcome) => void
  /** Called once when the run ends, however it ends. */
  onFinish?: (state: DayRunState) => void
  /** Called when one request could not be run; the loop carries on to the next. */
  onError?: (sample: Sample, error: unknown) => void
}

function initial(total: number, label: string): DayRunState {
  return { done: 0, total, quiet: 0, cards: 0, failed: 0, label, running: true, stopped: false }
}

export function useDayRun(options: DayRunOptions = {}): DayRun {
  const [progress, setProgress] = useState<DayRunState | null>(null)
  const cancelled = useRef(false)
  const inFlight = useRef(false)
  /** Latest callbacks, so a run started three renders ago still calls the current ones. */
  const handlers = useRef(options)
  useEffect(() => {
    handlers.current = options
  })

  // A run outlives the screen it started on: stop it when the app unmounts.
  useEffect(
    () => () => {
      cancelled.current = true
    },
    [],
  )

  const stop = useCallback(() => {
    cancelled.current = true
    setProgress((current) =>
      current && current.running ? { ...current, running: false, stopped: true, label: null } : current,
    )
  }, [])

  const clear = useCallback(() => {
    cancelled.current = true
    setProgress(null)
  }, [])

  const start = useCallback((samples: Sample[], count: number) => {
    if (inFlight.current) return
    const queue = demoSequence(samples, count)
    if (queue.length === 0) return

    cancelled.current = false
    inFlight.current = true
    let state = initial(queue.length, queue[0]!.label)
    setProgress(state)

    const advance = (patch: Partial<DayRunState>) => {
      state = { ...state, ...patch }
      setProgress(state)
    }

    void (async () => {
      try {
        for (const [index, sample] of queue.entries()) {
          if (cancelled.current) break
          advance({ label: sample.label })
          try {
            const outcome = await postInbox({
              text: sample.text,
              source: sample.source ?? 'sms',
              contact: sample.contact ?? undefined,
            })
            const needsYou = outcome.interrupted || outcome.decisions_created.length > 0
            advance({
              done: index + 1,
              quiet: state.quiet + (needsYou ? 0 : 1),
              cards: state.cards + (needsYou ? 1 : 0),
            })
            handlers.current.onOutcome?.(sample, outcome)
          } catch (error) {
            if (cancelled.current) break
            advance({ done: index + 1, failed: (state.failed ?? 0) + 1 })
            handlers.current.onError?.(sample, error)
          }
        }
      } finally {
        inFlight.current = false
        const finished: DayRunState = {
          ...state,
          running: false,
          stopped: cancelled.current,
          label: null,
        }
        setProgress(finished)
        handlers.current.onFinish?.(finished)
      }
    })()
  }, [])

  return { progress, running: progress?.running ?? false, start, stop, clear }
}
