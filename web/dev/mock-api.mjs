#!/usr/bin/env node
/**
 * Porchlight dev mock API — zero dependencies, Node >= 20.
 *
 * Implements every endpoint in docs/CONTRACTS.md §9 with fixture data so the whole
 * UI (including SSE, decisions, and the demo console) can be exercised without the
 * Python backend. `npm run dev:mock` runs this alongside Vite on :8000.
 *
 * It is stateful for the life of the process: POST /api/inbox really creates a
 * request and streams intake → matcher → outreach → steward over ~4s, resolving a
 * decision really resumes the request, and /api/demo/run_day walks a Tuesday.
 */

import { createServer } from 'node:http'
import {
  GROUP_SETTINGS,
  SAMPLES,
  hoursAhead,
  newId,
  seedDecisions,
  seedLog,
  seedMessages,
  seedRequesters,
  seedRequests,
  seedVolunteers,
} from './fixtures.mjs'

const PORT = Number(process.env.PORT ?? 8000)
const now = () => new Date().toISOString()
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))
const pick = (list) => list[Math.floor(Math.random() * list.length)]

/* ------------------------------------------------------------------ state */

let state
function reseed() {
  state = {
    volunteers: seedVolunteers(),
    requesters: seedRequesters(),
    requests: seedRequests(),
    decisions: seedDecisions(),
    log: seedLog(),
    messages: seedMessages(),
    settings: { ...GROUP_SETTINGS },
  }
}
reseed()

/* -------------------------------------------------------------------- SSE */

const clients = new Set()

function emit(event) {
  const payload = JSON.stringify({
    type: event.type,
    ts: event.ts ?? now(),
    request_id: event.request_id ?? null,
    agent: event.agent ?? null,
    summary: event.summary ?? '',
    detail: event.detail ?? {},
  })
  for (const client of clients) {
    try {
      client.write(`data: ${payload}\n\n`)
    } catch {
      clients.delete(client)
    }
  }
}

setInterval(() => {
  for (const client of clients) {
    try {
      client.write(': keep-alive\n\n')
    } catch {
      clients.delete(client)
    }
  }
  emit({ type: 'heartbeat', summary: 'still here' })
}, 15_000).unref()

/* ---------------------------------------------------------------- helpers */

function addLog({ agent, kind, summary, detail = {}, request_id = null, autonomous = true }) {
  const entry = {
    id: newId('log'),
    ts: now(),
    request_id,
    agent,
    kind,
    summary,
    detail,
    autonomous,
  }
  state.log.unshift(entry)
  emit({ type: 'log', request_id, agent, summary, detail: { ...detail, kind, log_id: entry.id } })
  return entry
}

function requestById(id) {
  return state.requests.find((r) => r.id === id) ?? null
}

function statusLine() {
  const open = state.decisions.filter((d) => d.status === 'open').length
  const handled = handledAutonomously()
  const head = open === 0 ? 'All quiet.' : open <= 2 ? 'Quiet.' : 'Busy evening.'
  const need = open === 0 ? 'nothing needs you' : `${open} need${open === 1 ? 's' : ''} you`
  return `${head} ${handled} handled today · ${need}.`
}

function handledAutonomously() {
  const withCards = new Set(state.decisions.map((d) => d.request_id))
  return state.requests.filter(
    (r) => !withCards.has(r.id) && ['confirmed', 'in_progress', 'completed'].includes(r.status),
  ).length
}

function stats() {
  const byStatus = {}
  for (const r of state.requests) byStatus[r.status] = (byStatus[r.status] ?? 0) + 1
  return {
    handled_autonomously: handledAutonomously(),
    decisions_open: state.decisions.filter((d) => d.status === 'open').length,
    decisions_resolved: state.decisions.filter((d) => d.status === 'resolved').length,
    requests_by_status: byStatus,
    confirmed_this_week: state.requests.filter((r) =>
      ['confirmed', 'in_progress', 'completed'].includes(r.status),
    ).length,
    volunteers_active: state.volunteers.filter((v) => v.load.this_week > 0).length,
  }
}

/* ------------------------------------------------------- intake behaviour */

const FLAGS = [
  { re: /\b(home )?alone\b|\bunattended\b|\bstove\b|\bchest pain\b|\bthreat(en(ing|ed)?)?\b|\bself.?harm\b|\bab(use|using)\b/i, kind: 'safety' },
  { re: /\bmoney\b|\bbill\b|\bcash\b|\bgift ?card\b|\bpay (for|back)\b|\$\s?\d+|\bfunds?\b|\bafford\b/i, kind: 'money' },
  { re: /\bin.?home\b|\bsit with (her|him|them)\b|\bstay with\b/i, kind: 'vetting' },
  { re: /\bfelt off\b|\bnot go back\b|\buncomfortable\b|\bconcern(ed)?\b/i, kind: 'concern' },
]

function classify(text) {
  for (const flag of FLAGS) if (flag.re.test(text)) return flag.kind
  return null
}

function categorise(text) {
  const t = text.toLowerCase()
  if (/(ride|lift|drive|drop.?off|appointment|airport|dialysis)/.test(t)) return 'ride'
  if (/(grocer|shop|milk|bread|food bank)/.test(t)) return 'groceries'
  if (/(meal|tray|cook|dinner|lunch)/.test(t)) return 'meal'
  if (/(snow|shovel|lawn|mow|eavestrough|yard|clean)/.test(t)) return 'chore'
  if (/(tv|wifi|internet|computer|phone|tablet|signal)/.test(t)) return 'tech'
  if (/(visit|company|lonely|companion|sit with)/.test(t)) return 'companionship'
  if (/(translat|letter|interpret)/.test(t)) return 'translate'
  if (/(kid|child|babysit|daycare)/.test(t)) return 'childcare'
  if (/(prescription|pharmacy|pick ?up|errand|post office)/.test(t)) return 'errand'
  return 'other'
}

function summarise(text) {
  const clean = text.replace(/\[[^\]]*\]/g, '').replace(/\s+/g, ' ').trim()
  const first = clean.split(/(?<=[.?!])\s/)[0] ?? clean
  const short = first.length > 96 ? `${first.slice(0, 93)}…` : first
  return short.charAt(0).toUpperCase() + short.slice(1)
}

const DECISION_BLUEPRINTS = {
  safety: (request, requester) => ({
    title: 'Danger language — Porchlight stopped before contacting anyone',
    context:
      `A ${request.source} message arrived from **${requester?.name ?? 'an unknown contact'}**` +
      `${requester && requester.history_count <= 2 ? ' (first-time requester)' : ''}:\n\n` +
      `"${request.raw_text}"\n\n` +
      'The safety policy **denies** autonomous outreach on danger language. No volunteer has been contacted. ' +
      'A reply draft telling them to call **emergency services** is queued and unsent.',
    recommendation: 'Send the emergency-services reply and follow up yourself. This is not a volunteer dispatch.',
    options: [
      { id: 'i_will_handle', label: 'I’ll handle it', description: 'Send the 911 reply and take it off Porchlight.' },
      { id: 'approve', label: 'Send reply, keep watching', description: 'Send the draft and keep the request open.' },
      { id: 'decline_request', label: 'Close — not for us', description: 'Close with a note. Nobody is contacted.' },
    ],
  }),
  money: (request, requester) => ({
    title: `A request involving money from ${requester?.name ?? 'a neighbour'}`,
    context:
      `"${request.raw_text}"\n\n` +
      `- Group petty-cash limit: **$${GROUP_SETTINGS.petty_cash_limit.toFixed(2)}**\n` +
      `- Past requests from this contact: **${requester?.history_count ?? 0}**\n\n` +
      'Porchlight has promised nothing and asked no volunteer for money. The money policy requires you first.',
    recommendation: 'Refer to the city arrears program and offer a grocery run instead, so cash goes to the bill.',
    options: [
      { id: 'approve', label: 'Approve from petty cash', description: 'Records an exception in the log.' },
      { id: 'i_will_handle', label: 'I’ll call them', description: 'Coordinator takes it; Porchlight stops here.' },
      { id: 'decline_request', label: 'Refer, don’t fund', description: 'Send the referral and offer help in kind.' },
    ],
  }),
  vetting: (request, requester) => ({
    title: 'First-time requester asking for in-home help',
    context:
      `"${request.raw_text}"\n\n` +
      `**${requester?.name ?? 'This contact'}** is new to the group and the request is inside the home. ` +
      'The vetting policy holds in-home matches for a new requester until you confirm.',
    recommendation: 'Approve with a **childcare-cleared, vetted** volunteer only — Grace Boateng fits.',
    options: [
      { id: 'approve', label: 'Approve, vetted only', description: 'Match from the vetted pool.' },
      { id: 'i_will_handle', label: 'I’ll visit first', description: 'Coordinator does the intro visit.' },
      { id: 'decline_request', label: 'Decline for now', description: 'Send a warm decline with alternatives.' },
    ],
  }),
  concern: (request) => ({
    title: 'A volunteer raised a concern',
    context: `"${request.raw_text}"\n\nPorchlight paused outreach on this thread and did not reassign anyone.`,
    recommendation: 'Call the volunteer, then decide whether the address gets paired visits only.',
    options: [
      { id: 'i_will_handle', label: 'I’ll call them', description: 'Coordinator follows up directly.' },
      { id: 'widen_pool', label: 'Pair visits only', description: 'Require two volunteers for this address.' },
      { id: 'decline_request', label: 'Stop serving this address', description: 'Closes with a note in memory.' },
    ],
  }),
  unmatched: (request) => ({
    title: 'Nobody free before the window closes',
    context: `**${request.summary}**\n\nThree asks, no acceptance, and the window opens soon.`,
    recommendation: 'Widen the pool to neighbouring zones before rescheduling.',
    options: [
      { id: 'widen_pool', label: 'Widen the pool', description: 'Include neighbouring zones.' },
      { id: 'reschedule', label: 'Reschedule', description: 'Push the window out.' },
      { id: 'i_will_handle', label: 'I’ll take it', description: 'Coordinator covers it personally.' },
    ],
  }),
}

function createDecision(request, kind) {
  const requester = state.requesters.find((r) => r.id === request.requester_id) ?? null
  const build = DECISION_BLUEPRINTS[kind] ?? DECISION_BLUEPRINTS.unmatched
  const blueprint = build(request, requester)
  const decision = {
    id: newId('dec'),
    request_id: request.id,
    kind,
    ...blueprint,
    interrupt_id: newId('int'),
    session_id: request.id,
    node: 'intake',
    status: 'open',
    resolved_option: null,
    resolved_note: null,
    created_at: now(),
    resolved_at: null,
  }
  state.decisions.unshift(decision)
  emit({
    type: 'decision',
    request_id: request.id,
    agent: 'policy',
    summary: `Decision card raised: ${decision.title}`,
    detail: { decision_id: decision.id, kind },
  })
  return decision
}

function findRequester(contact, text) {
  if (contact) {
    const hit = state.requesters.find(
      (r) => r.contact.toLowerCase() === contact.toLowerCase() || r.name.toLowerCase() === contact.toLowerCase(),
    )
    if (hit) return hit
  }
  const named = state.requesters.find((r) => text.toLowerCase().includes(r.name.split(' ')[0].toLowerCase()))
  return named ?? null
}

/** Streams a request through the graph, emitting trace events for ~4 seconds. */
async function runRequest(request, { fast = false } = {}) {
  const beat = (ms) => sleep(fast ? Math.round(ms / 5) : ms)
  const requester = state.requesters.find((r) => r.id === request.requester_id) ?? null
  const decisions = []

  emit({ type: 'node_start', request_id: request.id, agent: 'intake', summary: 'intake started', detail: { node: 'intake', source: request.source } })
  await beat(320)

  emit({ type: 'tool_call', request_id: request.id, agent: 'intake', summary: 'lookup_requester_history', detail: { tool: 'lookup_requester_history', input: { contact_or_name: requester?.contact ?? 'unknown' } } })
  await beat(340)
  emit({ type: 'tool_result', request_id: request.id, agent: 'intake', summary: requester ? `${requester.name} — ${requester.history_count} past requests` : 'No history — new contact', detail: { tool: 'lookup_requester_history', matched: requester?.id ?? null } })
  addLog({
    agent: 'intake',
    kind: 'tool_call',
    summary: requester
      ? `Matched ${requester.name} — ${requester.history_count} past requests`
      : 'New contact, no history on file',
    detail: { tool: 'lookup_requester_history', matched: requester?.id ?? null },
    request_id: request.id,
  })
  await beat(300)

  emit({ type: 'model_call', request_id: request.id, agent: 'intake', summary: 'claude-haiku-4-5 · structured output AidRequest', detail: { model: 'claude-haiku-4-5', tokens_in: 640 + Math.floor(Math.random() * 400), tokens_out: 120 + Math.floor(Math.random() * 120) } })
  await beat(420)
  request.status = 'triaging'
  request.updated_at = now()
  addLog({ agent: 'intake', kind: 'model', summary: `Parsed as a ${request.category} request — ${request.summary}`, detail: { category: request.category, urgency: request.urgency }, request_id: request.id })
  emit({ type: 'node_end', request_id: request.id, agent: 'intake', summary: 'intake finished', detail: { node: 'intake' } })
  await beat(260)

  const flag = classify(request.raw_text)
  if (flag) {
    request.status = 'escalated'
    request.updated_at = now()
    if (flag === 'safety') request.safety_flags = ['danger_language']
    if (flag === 'money') request.money_involved = true
    addLog({
      agent: 'intake',
      kind: 'policy',
      summary:
        flag === 'safety'
          ? 'Danger language detected — autonomous outreach denied'
          : flag === 'money'
            ? 'Money involved — held before any commitment'
            : flag === 'vetting'
              ? 'New requester asking for in-home help — held for vetting'
              : 'A concern was raised — outreach paused',
      detail: { rule: `${flag}.policy`, action: flag === 'safety' ? 'Deny' : 'Confirm' },
      request_id: request.id,
      autonomous: false,
    })
    await beat(700)
    const decision = createDecision(request, flag)
    decisions.push(decision)
    addLog({ agent: 'policy', kind: 'decision', summary: `Raised a ${flag} card: ${decision.title}`, detail: { decision_id: decision.id, kind: flag }, request_id: request.id, autonomous: false })
    return {
      request_id: request.id,
      status: request.status,
      decisions_created: decisions,
      log_events: 4,
      interrupted: true,
      summary: 'Paused for the coordinator. The porch light is on.',
    }
  }

  /* ---- matcher ---- */
  emit({ type: 'node_start', request_id: request.id, agent: 'matcher', summary: 'matcher started', detail: { node: 'matcher' } })
  await beat(280)
  const pool = state.volunteers.filter(
    (v) => v.vetted && v.load.this_week < v.max_per_week && (!request.location_zone || v.zones.includes(request.location_zone)),
  )
  const candidates = (pool.length ? pool : state.volunteers.filter((v) => v.vetted)).slice(0, 3)
  const chosen = candidates[0] ?? state.volunteers[0]
  const confidence = Number((0.7 + Math.random() * 0.28).toFixed(2))
  emit({ type: 'tool_call', request_id: request.id, agent: 'matcher', summary: 'find_candidates', detail: { tool: 'find_candidates', input: { request_id: request.id, limit: 3 } } })
  await beat(340)
  emit({ type: 'tool_result', request_id: request.id, agent: 'matcher', summary: candidates.map((c) => c.name).join(' · '), detail: { candidates: candidates.map((c) => c.id), confidence } })
  addLog({ agent: 'matcher', kind: 'tool_call', summary: `Ranked ${candidates.length} candidates — ${chosen.name} first (${confidence})`, detail: { tool: 'find_candidates', top: candidates.map((c) => c.id), confidence }, request_id: request.id })
  request.status = 'matching'
  emit({ type: 'node_end', request_id: request.id, agent: 'matcher', summary: 'matcher finished', detail: { node: 'matcher', confidence } })
  await beat(300)

  /* ---- outreach ---- */
  emit({ type: 'node_start', request_id: request.id, agent: 'outreach', summary: 'outreach started', detail: { node: 'outreach' } })
  const body = `Hi ${chosen.name.split(' ')[0]} — ${request.summary.toLowerCase()}. You're closest and free this week. Any chance? No pressure, I'll ask the next person if not.`
  const message = {
    id: newId('msg'),
    request_id: request.id,
    to: 'volunteer',
    recipient_id: chosen.id,
    channel: 'sms',
    body,
    scheduled_for: null,
    sent_at: now(),
    status: 'sent',
  }
  state.messages.unshift(message)
  request.status = 'awaiting_reply'
  request.attempts.push({ volunteer_id: chosen.id, sent_at: now(), outcome: 'pending', note: null })
  emit({ type: 'message', request_id: request.id, agent: 'outreach', summary: `→ ${chosen.name}: ${body.slice(0, 60)}…`, detail: { to: 'volunteer', recipient_id: chosen.id } })
  addLog({ agent: 'outreach', kind: 'message_sent', summary: `Asked ${chosen.name} — address withheld until they accept`, detail: { to: 'volunteer', recipient_id: chosen.id, redacted: ['address'] }, request_id: request.id })
  await beat(520)

  emit({ type: 'tool_call', request_id: request.id, agent: 'outreach', summary: 'read_replies', detail: { tool: 'read_replies' } })
  await beat(340)
  const attempt = request.attempts[request.attempts.length - 1]
  attempt.outcome = 'accepted'
  attempt.note = pick(['Yes, happy to.', 'I can do that.', 'Sure — I’m going that way anyway.'])
  emit({ type: 'tool_result', request_id: request.id, agent: 'outreach', summary: `${chosen.name} accepted`, detail: { intent: 'accept', confidence: 0.96 } })
  addLog({ agent: 'outreach', kind: 'tool_call', summary: `${chosen.name} accepted — assigned and address released`, detail: { tool: 'assign_volunteer', volunteer_id: chosen.id }, request_id: request.id })
  request.assigned_volunteer_id = chosen.id
  request.status = 'confirmed'
  chosen.load.this_week += 1
  chosen.stats.accepted += 1
  chosen.stats.last_active = now()
  chosen.load.last_active = now()
  emit({ type: 'node_end', request_id: request.id, agent: 'outreach', summary: 'outreach finished', detail: { node: 'outreach' } })
  await beat(280)

  /* ---- steward ---- */
  emit({ type: 'node_start', request_id: request.id, agent: 'steward', summary: 'steward started', detail: { node: 'steward' } })
  const confirmBody = `Good news — ${chosen.name} is covering this. They have your number if anything changes.`
  state.messages.unshift({
    id: newId('msg'),
    request_id: request.id,
    to: 'requester',
    recipient_id: request.requester_id,
    channel: 'sms',
    body: confirmBody,
    scheduled_for: null,
    sent_at: now(),
    status: 'sent',
  })
  emit({ type: 'message', request_id: request.id, agent: 'steward', summary: `→ ${requester?.name ?? 'requester'}: ${confirmBody.slice(0, 52)}…`, detail: { to: 'requester' } })
  addLog({ agent: 'steward', kind: 'message_sent', summary: `Confirmed with ${requester?.name ?? 'the requester'} and scheduled a reminder`, detail: { to: 'requester', reminder_at: hoursAhead(20) }, request_id: request.id })
  await beat(300)
  addLog({ agent: 'steward', kind: 'memory', summary: `Remembered: ${chosen.name} covers ${request.category} in ${request.location_zone ?? 'this zone'}`, detail: { about_id: chosen.id, kind: 'fact' }, request_id: request.id })
  emit({ type: 'node_end', request_id: request.id, agent: 'steward', summary: 'steward finished', detail: { node: 'steward' } })
  request.updated_at = now()

  return {
    request_id: request.id,
    status: request.status,
    decisions_created: [],
    log_events: 6,
    interrupted: false,
    summary: `Handled quietly — ${chosen.name} confirmed. Nothing needed you.`,
  }
}

function createRequestFromText({ text, source = 'form', contact, image_base64 }) {
  const requester = findRequester(contact, text)
  const request = {
    id: newId('req'),
    source,
    raw_text: image_base64 ? `[photo of paper slip] ${text}` : text,
    requester_id: requester?.id ?? null,
    category: categorise(text),
    summary: summarise(text),
    window_start: hoursAhead(12),
    window_end: hoursAhead(20),
    flexible: true,
    location_zone: requester?.zone ?? pick(GROUP_SETTINGS.zones),
    constraints: [],
    urgency: /urgent|today|tonight|asap|tomorrow/i.test(text) ? 'high' : 'normal',
    money_involved: false,
    safety_flags: [],
    first_time_requester: !requester || requester.history_count <= 2,
    status: 'new',
    assigned_volunteer_id: null,
    attempts: [],
    created_at: now(),
    updated_at: now(),
  }
  state.requests.unshift(request)
  return request
}

/* ------------------------------------------------------------ run a day */

let dayRunning = false
async function runDay(count) {
  if (dayRunning) return
  dayRunning = true
  let quiet = 0
  let cards = 0
  emit({ type: 'demo_progress', agent: 'system', summary: `Running a Tuesday — ${count} requests`, detail: { done: 0, total: count, quiet, cards } })
  const deck = [...SAMPLES].sort(() => Math.random() - 0.5)
  for (let index = 0; index < count; index += 1) {
    const sample = deck[index % deck.length]
    const request = createRequestFromText({ text: sample.text, source: sample.source ?? 'sms' })
    const outcome = await runRequest(request, { fast: true })
    if (outcome.interrupted) cards += 1
    else quiet += 1
    emit({
      type: 'demo_progress',
      request_id: request.id,
      agent: 'system',
      summary: `${index + 1} of ${count} — ${outcome.interrupted ? 'needs you' : 'handled quietly'}`,
      detail: { done: index + 1, total: count, quiet, cards },
    })
    await sleep(260)
  }
  addLog({ agent: 'brief', kind: 'model', summary: `Tuesday complete — ${quiet} handled quietly, ${cards} needed you`, detail: { quiet, cards, total: count }, autonomous: true })
  dayRunning = false
}

/* ------------------------------------------------------------- resolution */

function resolveDecision(decision, optionId, note) {
  const option = decision.options.find((o) => o.id === optionId) ?? decision.options[0]
  decision.status = 'resolved'
  decision.resolved_option = option.id
  decision.resolved_note = note ?? null
  decision.resolved_at = now()

  const request = decision.request_id ? requestById(decision.request_id) : null
  addLog({
    agent: 'policy',
    kind: 'decision',
    summary: `You chose "${option.label}" — Porchlight resumed at the ${decision.node ?? 'intake'} step`,
    detail: { decision_id: decision.id, option: option.id, note: note ?? null },
    request_id: decision.request_id,
    autonomous: false,
  })
  emit({ type: 'decision', request_id: decision.request_id, agent: 'policy', summary: `Resolved: ${option.label}`, detail: { decision_id: decision.id, option: option.id, status: 'resolved' } })

  let summary = 'Resumed.'
  if (request) {
    if (option.id === 'i_will_handle') {
      request.status = 'escalated'
      summary = 'Handed to you. Porchlight will not act on this one.'
      addLog({ agent: 'steward', kind: 'message_sent', summary: 'Told the requester a coordinator will call them directly', detail: { to: 'requester' }, request_id: request.id })
    } else if (option.id === 'decline_request') {
      request.status = 'declined'
      summary = 'Closed with a warm decline and an alternative.'
      addLog({ agent: 'steward', kind: 'message_sent', summary: 'Sent a warm decline with two alternatives', detail: { to: 'requester' }, request_id: request.id })
    } else if (option.id === 'reschedule') {
      request.status = 'matching'
      request.window_start = hoursAhead(96)
      request.window_end = hoursAhead(104)
      summary = 'Window moved out a week; matching again.'
      addLog({ agent: 'matcher', kind: 'tool_call', summary: 'Window moved out a week — re-running the match', detail: { tool: 'update_request' }, request_id: request.id })
    } else if (option.id === 'widen_pool') {
      request.status = 'matching'
      summary = 'Pool widened to neighbouring zones; asking again.'
      addLog({ agent: 'matcher', kind: 'tool_call', summary: 'Pool widened to neighbouring zones — 4 new candidates', detail: { tool: 'find_candidates', widened: true }, request_id: request.id })
    } else {
      request.status = 'matching'
      summary = 'Approved. Porchlight is back on it.'
      addLog({ agent: 'outreach', kind: 'message_sent', summary: 'Approved — outreach resumed with the recommended volunteer', detail: { to: 'volunteer' }, request_id: request.id })
    }
    request.updated_at = now()
  }

  return {
    request_id: decision.request_id ?? '',
    status: request?.status ?? 'escalated',
    decisions_created: [],
    log_events: 2,
    interrupted: false,
    summary,
  }
}

/* ------------------------------------------------------------------ HTTP */

function send(res, status, body, headers = {}) {
  const payload = body === undefined ? '' : JSON.stringify(body)
  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': '*',
    'Access-Control-Allow-Methods': 'GET,POST,OPTIONS',
    'Cache-Control': 'no-store',
    ...headers,
  })
  res.end(payload)
}

async function readJson(req) {
  const chunks = []
  for await (const chunk of req) chunks.push(chunk)
  if (!chunks.length) return {}
  try {
    return JSON.parse(Buffer.concat(chunks).toString('utf8'))
  } catch {
    return {}
  }
}

const server = createServer(async (req, res) => {
  const url = new URL(req.url ?? '/', `http://localhost:${PORT}`)
  const path = url.pathname.replace(/\/+$/, '') || '/'
  const method = req.method ?? 'GET'

  if (method === 'OPTIONS') return send(res, 204)

  /* SSE */
  if (path === '/api/events') {
    res.writeHead(200, {
      'Content-Type': 'text/event-stream; charset=utf-8',
      'Cache-Control': 'no-cache, no-transform',
      Connection: 'keep-alive',
      'X-Accel-Buffering': 'no',
      'Access-Control-Allow-Origin': '*',
    })
    res.write('retry: 2000\n\n')
    clients.add(res)
    res.write(
      `data: ${JSON.stringify({ type: 'log', ts: now(), request_id: null, agent: 'system', summary: 'Trace connected — the mock porch is listening', detail: { kind: 'policy', clients: clients.size } })}\n\n`,
    )
    req.on('close', () => clients.delete(res))
    return
  }

  if (path === '/api/health') return send(res, 200, { status: 'ok', mode: 'mock', version: 'dev' })

  if (path === '/api/porch') {
    return send(res, 200, {
      status_line: statusLine(),
      light_on: state.decisions.some((d) => d.status === 'open'),
      open_decisions: state.decisions.filter((d) => d.status === 'open'),
      quiet_log: state.log.slice(0, 60),
      stats: stats(),
      group: state.settings,
    })
  }

  if (path === '/api/requests' && method === 'GET') {
    const status = url.searchParams.get('status')
    const rows = status ? state.requests.filter((r) => r.status === status) : state.requests
    return send(res, 200, rows)
  }

  const requestMatch = path.match(/^\/api\/requests\/([^/]+)$/)
  if (requestMatch && method === 'GET') {
    const request = requestById(decodeURIComponent(requestMatch[1]))
    if (!request) return send(res, 404, { detail: 'request not found' })
    return send(res, 200, {
      request,
      attempts: request.attempts,
      messages: state.messages.filter((m) => m.request_id === request.id),
      log: state.log.filter((l) => l.request_id === request.id),
    })
  }

  if (path === '/api/decisions' && method === 'GET') {
    const status = url.searchParams.get('status')
    const rows = status ? state.decisions.filter((d) => d.status === status) : state.decisions
    return send(res, 200, rows)
  }

  const resolveMatch = path.match(/^\/api\/decisions\/([^/]+)\/resolve$/)
  if (resolveMatch && method === 'POST') {
    const decision = state.decisions.find((d) => d.id === decodeURIComponent(resolveMatch[1]))
    if (!decision) return send(res, 404, { detail: 'decision not found' })
    if (decision.status === 'resolved') return send(res, 409, { detail: 'already resolved' })
    const body = await readJson(req)
    await sleep(320)
    return send(res, 200, resolveDecision(decision, body.option_id, body.note))
  }

  if (path === '/api/volunteers' && method === 'GET') return send(res, 200, state.volunteers)

  if (path === '/api/log' && method === 'GET') {
    const requestId = url.searchParams.get('request_id')
    const limit = Number(url.searchParams.get('limit') ?? 200)
    const rows = requestId ? state.log.filter((l) => l.request_id === requestId) : state.log
    return send(res, 200, rows.slice(0, limit))
  }

  if (path === '/api/inbox' && method === 'POST') {
    const body = await readJson(req)
    if (!body.text || !String(body.text).trim()) return send(res, 422, { detail: 'text is required' })
    const request = createRequestFromText({
      text: String(body.text).trim(),
      source: body.source ?? 'form',
      contact: body.contact,
      image_base64: body.image_base64,
    })
    const outcome = await runRequest(request)
    return send(res, 200, outcome)
  }

  if (path === '/api/demo/samples' && method === 'GET') return send(res, 200, SAMPLES)

  if (path === '/api/demo/run_day' && method === 'POST') {
    const body = await readJson(req)
    const count = Math.max(1, Math.min(24, Number(body.count ?? 12)))
    void runDay(count)
    return send(res, 202, { started: true, count })
  }

  if (path === '/api/demo/reset' && method === 'POST') {
    reseed()
    emit({ type: 'log', agent: 'system', summary: 'Demo reset — fixtures reseeded', detail: { kind: 'policy' } })
    return send(res, 200, { ok: true })
  }

  if (path === '/api/sweep' && method === 'POST') {
    const stale = state.requests.filter((r) => r.status === 'awaiting_reply')
    for (const request of stale) {
      addLog({ agent: 'outreach', kind: 'policy', summary: `Swept ${request.summary} — no reply yet, next candidate queued`, detail: { rule: 'sweep.stale_outreach' }, request_id: request.id })
    }
    return send(res, 200, {
      messages_sent: stale.length,
      escalated: [],
      timed_out: stale.map((r) => r.id),
      summary: `Swept ${stale.length} stale thread${stale.length === 1 ? '' : 's'}.`,
    })
  }

  if (path === '/api/brief' && method === 'GET') {
    const s = stats()
    return send(res, 200, {
      markdown:
        `## ${state.settings.name} — daily brief\n\n` +
        `**${s.handled_autonomously} handled without you.** ${s.decisions_open} card${s.decisions_open === 1 ? '' : 's'} open.\n\n` +
        `- Confirmed this week: ${s.confirmed_this_week}\n` +
        `- Volunteers active: ${s.volunteers_active} of ${state.volunteers.length}\n` +
        `- Rides are up 3x on last month — mostly dialysis.\n`,
    })
  }

  return send(res, 404, { detail: `no route for ${method} ${path}` })
})

server.listen(PORT, () => {
  process.stdout.write(
    `porchlight mock api → http://localhost:${PORT}/api  (${state.volunteers.length} volunteers, ${state.requests.length} requests, ${state.decisions.filter((d) => d.status === 'open').length} open cards)\n`,
  )
})
