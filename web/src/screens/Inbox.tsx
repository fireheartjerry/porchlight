/**
 * Screen 4 — Inbox, the demo console (docs/UI.md §Screens 4).
 *
 * Pick or paste something a group actually received, send it, and watch what
 * Porchlight does: either it carries the job on its own, or the lantern lights.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useState, useSyncExternalStore } from 'react'
import { getSamples, postInbox, qk, resetDemo, runDay } from '../api'
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
import { useEvents } from '../hooks/useEvents'
import { useToast } from '../hooks/useToast'
import type { Sample, Source } from '../types'

export function Inbox() {
  const queryClient = useQueryClient()
  const toast = useToast()
  const { demoProgress, clearDemoProgress } = useEvents()

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

  const tuesday = useMutation({
    mutationFn: () => runDay(count),
    onSuccess: (result) =>
      toast.push({
        title: 'Running a Tuesday.',
        description: `${result.count} requests, start to finish. Watch the Trace.`,
        tone: 'quiet',
      }),
    onError: (error) =>
      toast.push({
        title: 'The day wouldn’t start.',
        description: error instanceof Error ? error.message : 'Unknown error',
        tone: 'bad',
      }),
  })

  const reset = useMutation({
    mutationFn: resetDemo,
    onSuccess: () => {
      clearDemoProgress()
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
        progress={demoProgress}
        count={count}
        onCountChange={setCount}
        onRun={() => tuesday.mutate()}
        running={tuesday.isPending}
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

function summarise(text: string): string {
  const clean = text.replace(/\s+/g, ' ').trim()
  return clean.length > 64 ? `${clean.slice(0, 61)}…` : clean || 'Untitled message'
}
