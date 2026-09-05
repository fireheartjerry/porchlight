/**
 * Screen 4 — Inbox, the demo console (docs/UI.md §Screens 4).
 *
 * Pick or paste something a group actually received, send it, and watch what
 * Porchlight does: either it carries the job on its own, or the lantern lights.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useState, useSyncExternalStore } from 'react'
import { getSamples, postInbox, qk, resetDemo } from '../api'
import { Card } from '../components/Card'
import { SectionLabel } from '../components/Card'
import { EmptyState } from '../components/EmptyState'
import { QueryState, Screen, Skeleton } from '../components/Screen'
import { Composer, type PaperSlip } from '../components/inbox/Composer'
import { DayRunner } from '../components/inbox/DayRunner'
import { OutcomePanel, OutcomeRow } from '../components/inbox/OutcomePanel'
import { clearSends, getSends, pushSend, subscribeSends } from '../components/inbox/sendLog'
import { SampleList } from '../components/inbox/SampleList'
import { setOpenRequest } from '../components/requests/openRequest'
import { useDayRun, type DayRunState } from '../hooks/useDayRun'
import { useEvents } from '../hooks/useEvents'
import { useToast } from '../hooks/useToast'
import type { DemoProgress, Sample, Source } from '../types'

export function Inbox() {
  const queryClient = useQueryClient()
  const toast = useToast()
  const { demoProgress } = useEvents()

  const samples = useQuery({ queryKey: qk.samples, queryFn: getSamples })

  const [text, setText] = useState('')
  const [source, setSource] = useState<Source>('form')
  const [contact, setContact] = useState('')
  const [slip, setSlip] = useState<PaperSlip | null>(null)
  const [activeSample, setActiveSample] = useState<string | null>(null)
  const [count, setCount] = useState(12)
  /** Outside React, so the result panel survives a trip to the board and back. */
  const records = useSyncExternalStore(subscribeSends, getSends)

  const invalidateAll = useCallback(() => {
    for (const key of [['porch'], ['requests'], ['request'], ['decisions'], ['log'], ['volunteers']]) {
      void queryClient.invalidateQueries({ queryKey: key })
    }
  }, [queryClient])

  const goToRequest = useCallback((requestId: string) => {
    setOpenRequest(requestId)
    window.location.hash = '/requests'
  }, [])

  const goToPorch = useCallback(() => {
    window.location.hash = '/porch'
  }, [])

  const send = useMutation({
    mutationFn: () =>
      postInbox({
        text: text.trim(),
        source,
        contact: contact.trim() || undefined,
        image_base64: slip?.base64,
      }),
    onSuccess: (outcome) => {
      pushSend(summarise(text), outcome)
      setText('')
      setSlip(null)
      setActiveSample(null)
      invalidateAll()
      toast.push({
        title: outcome.interrupted ? 'The porch light is on.' : 'Handled quietly.',
        description: outcome.summary,
        tone: outcome.interrupted ? 'warn' : 'good',
      })
    },
    onError: (error) =>
      toast.push({
        title: 'Porchlight couldn’t take that in.',
        description: error instanceof Error ? error.message : 'Unknown error',
        tone: 'bad',
      }),
  })

  // The run happens here, in the browser: one POST /api/inbox per sample, in order.
  // A background task on the server would be frozen the moment its response was written.
  const tuesday = useDayRun({
    onOutcome: (sample, outcome) => {
      pushSend(sample.label, outcome)
      invalidateAll()
    },
    onError: (sample, error) =>
      toast.push({
        title: `“${sample.label}” didn’t come back.`,
        description: error instanceof Error ? error.message : 'Unknown error',
        tone: 'bad',
      }),
    onFinish: (state) => {
      invalidateAll()
      if (state.stopped && state.done === 0) return
      toast.push({
        title: state.stopped ? 'Tuesday stopped.' : 'Tuesday done.',
        description: `${state.quiet} handled quietly, ${state.cards} needed you.`,
        tone: state.cards > 0 ? 'warn' : 'good',
      })
    },
  })

  const reset = useMutation({
    mutationFn: resetDemo,
    onSuccess: () => {
      tuesday.clear()
      clearSends()
      invalidateAll()
      toast.push({ title: 'Demo reset.', description: 'Fixtures reseeded.', tone: 'quiet' })
    },
  })

  const onPickSample = (sample: Sample) => {
    setText(sample.text)
    setSource(sample.source ?? 'sms')
    setSlip(null)
    setActiveSample(sample.id)
  }

  const latest = records[0]
  const earlier = records.slice(1)

  return (
    <Screen
      title="Inbox"
      lede="Everything a group actually receives — a text, a form, a voicemail transcript, a photo of a paper slip. Drop one in and watch what Porchlight does with it."
    >
      <DayRunner
        progress={tuesday.progress ?? fromServer(demoProgress)}
        count={count}
        onCountChange={setCount}
        onRun={() => tuesday.start(samples.data ?? [], count)}
        onStop={tuesday.stop}
        running={tuesday.running}
        onReset={() => reset.mutate()}
        resetting={reset.isPending}
        onGoToPorch={goToPorch}
      />

      <div className="grid gap-5 lg:grid-cols-[minmax(0,21rem)_minmax(0,1fr)]">
        <section className="order-2 min-w-0 lg:order-1">
          <QueryState
            isPending={samples.isPending}
            error={samples.error}
            skeleton={
              <div className="space-y-2">
                {[0, 1, 2, 3, 4, 5].map((index) => (
                  <Skeleton key={index} className="h-14" />
                ))}
              </div>
            }
          >
            <div className="porch-scroll lg:sticky lg:top-[5.5rem] lg:max-h-[46rem] lg:overflow-y-auto lg:pr-1">
              <SampleList samples={samples.data ?? []} activeId={activeSample} onPick={onPickSample} />
            </div>
          </QueryState>
        </section>

        <section className="order-1 min-w-0 space-y-4 lg:order-2">
          <Composer
            text={text}
            onTextChange={(value) => {
              setText(value)
              setActiveSample(null)
            }}
            source={source}
            onSourceChange={setSource}
            contact={contact}
            onContactChange={setContact}
            slip={slip}
            onSlipChange={setSlip}
            onSend={() => send.mutate()}
            sending={send.isPending}
          />

          {latest ? (
            <OutcomePanel record={latest} onOpenRequest={goToRequest} onGoToPorch={goToPorch} />
          ) : (
            <Card>
              <EmptyState
                compact
                title="Nothing sent yet this session."
                body="Pick a sample on the left — the quiet ones show the machine working, the loud ones show it stopping."
              />
            </Card>
          )}

          {earlier.length > 0 && (
            <div>
              <SectionLabel className="mb-1.5 px-1" count={earlier.length}>
                Earlier this session
              </SectionLabel>
              <div className="porch-card px-2 py-1.5">
                {earlier.map((record) => (
                  <OutcomeRow key={record.key} record={record} onOpenRequest={goToRequest} />
                ))}
              </div>
            </div>
          )}
        </section>
      </div>
    </Screen>
  )
}

/**
 * `POST /api/demo/run_day` still exists for the local dev server and `scripts/run_day.py`.
 * When someone drives a Tuesday that way instead of from this button, its `demo_progress`
 * events fill the same bar — so watching from a second tab still shows the run.
 */
function fromServer(progress: DemoProgress | null): DayRunState | null {
  if (!progress) return null
  return {
    ...progress,
    failed: progress.failed ?? 0,
    label: progress.label ?? null,
    running: progress.done < progress.total,
    stopped: false,
  }
}

function summarise(text: string): string {
  const clean = text.replace(/\s+/g, ' ').trim()
  return clean.length > 64 ? `${clean.slice(0, 61)}…` : clean || 'Untitled message'
}
