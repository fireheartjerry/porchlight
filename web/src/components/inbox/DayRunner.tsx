/**
 * "Run a Tuesday": push a whole week-night of requests through the graph and watch
 * the split — how many Porchlight carried alone, how many it brought to you.
 *
 * The browser drives the run one `POST /api/inbox` at a time (see `useDayRun`), so
 * the bar below counts requests this tab actually finished rather than trusting a
 * background task on the server to still be alive.
 */

import clsx from 'clsx'
import { Play, RotateCcw, Square } from 'lucide-react'
import { Button } from '../Button'
import type { DayRunState } from '../../hooks/useDayRun'

const COUNTS = [6, 12, 20]

interface DayRunnerProps {
  progress: DayRunState | null
  count: number
  onCountChange: (count: number) => void
  onRun: () => void
  onStop: () => void
  running: boolean
  onReset: () => void
  resetting: boolean
  onGoToPorch: () => void
}

export function DayRunner({
  progress,
  count,
  onCountChange,
  onRun,
  onStop,
  running,
  onReset,
  resetting,
  onGoToPorch,
}: DayRunnerProps) {
  const pct = progress && progress.total > 0 ? Math.round((progress.done / progress.total) * 100) : 0
  const finished = progress !== null && !progress.running
  const failed = progress?.failed ?? 0

  return (
    <section className="porch-card relative mb-5 overflow-hidden px-5 py-4">
      {/* the pool of light this panel sits in */}
      <span
        aria-hidden
        className="pointer-events-none absolute -left-24 -top-28 h-56 w-72 rounded-full bg-[radial-gradient(circle,rgba(255,179,71,0.14),transparent_65%)]"
      />

      <div className="relative flex flex-wrap items-start justify-between gap-x-8 gap-y-4">
        <div className="min-w-[16rem] max-w-xl">
          <h2 className="font-display text-[1.05rem] leading-tight text-cream">Run a Tuesday</h2>
          <p className="mt-1 text-pretty text-[0.82rem] leading-snug text-cream-faint">
            A normal evening's worth of requests, start to finish: intake, matching, the asking, the
            declines, the confirmations. Most of it you will never have to read.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div
            role="radiogroup"
            aria-label="How many requests"
            className="flex overflow-hidden rounded-lg border border-white/[0.09]"
          >
            {COUNTS.map((option) => (
              <button
                key={option}
                type="button"
                role="radio"
                aria-checked={count === option}
                onClick={() => onCountChange(option)}
                className={clsx(
                  'tabnum px-3 py-1.5 text-[0.78rem] transition-colors duration-150',
                  count === option
                    ? 'bg-lamp/14 text-lamp-glow'
                    : 'text-cream-faint hover:bg-white/[0.05] hover:text-cream',
                )}
              >
                {option}
              </button>
            ))}
          </div>
          {running ? (
            <Button
              variant="quiet"
              size="sm"
              icon={<Square className="h-3.5 w-3.5" aria-hidden />}
              onClick={onStop}
            >
              Stop after this one
            </Button>
          ) : (
            <Button
              variant="primary"
              size="sm"
              icon={<Play className="h-3.5 w-3.5" aria-hidden />}
              onClick={onRun}
            >
              Run a Tuesday
            </Button>
          )}
          <Button
            variant="quiet"
            size="sm"
            icon={<RotateCcw className="h-3.5 w-3.5" aria-hidden />}
            loading={resetting}
            disabled={running}
            onClick={onReset}
          >
            Reset demo
          </Button>
        </div>
      </div>

      {progress && (
        <div className="relative mt-4 border-t border-white/[0.07] pt-3.5">
          <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
            <p className="text-[0.85rem] text-cream">
              {finished ? (
                <>
                  {progress.stopped ? 'Tuesday stopped' : 'Tuesday done'} —{' '}
                  <span className="tabnum text-sage">{progress.quiet}</span> handled quietly,{' '}
                  <span className="tabnum text-lamp-glow">{progress.cards}</span> needed you
                  {failed > 0 && (
                    <>
                      , <span className="tabnum text-ember">{failed}</span> didn’t come back
                    </>
                  )}
                  .
                </>
              ) : (
                <>
                  Working through the evening —{' '}
                  <span className="tabnum">{progress.done}</span> of{' '}
                  <span className="tabnum">{progress.total}</span>
                  {progress.label && <span className="text-cream-faint"> · {progress.label}</span>}
                </>
              )}
            </p>
            {finished ? (
              <button
                type="button"
                onClick={onGoToPorch}
                className="text-[0.78rem] text-lamp-glow underline-offset-4 hover:underline"
              >
                See what needs you →
              </button>
            ) : (
              <p className="tabnum text-[0.78rem] text-cream-faint">
                <span className="text-sage">{progress.quiet} quiet</span> ·{' '}
                <span className="text-lamp-glow">{progress.cards} need you</span>
                {failed > 0 && <span className="text-ember"> · {failed} failed</span>}
              </p>
            )}
          </div>

          <div
            className="mt-2.5 h-1.5 overflow-hidden rounded-full bg-white/[0.07]"
            role="progressbar"
            aria-valuenow={pct}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label="Tuesday progress"
          >
            <div
              className={clsx(
                'h-full rounded-full bg-gradient-to-r from-sage via-sage to-lamp transition-[width] duration-500',
                !finished && 'shadow-[0_0_14px_-2px_rgba(255,179,71,0.8)]',
              )}
              style={{ width: `${Math.max(pct, 2)}%` }}
            />
          </div>
        </div>
      )}
    </section>
  )
}
