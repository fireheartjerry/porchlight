/**
 * Fixture data for the dev mock API.
 *
 * Mirrors the shape of `porchlight/sim/fixtures.py` (docs/DESIGN.md §5). That module
 * does not exist yet at the time of writing; names, zones and skills here follow the
 * spec's "Maple Street Mutual Aid" group so the two can be reconciled cheaply later.
 */

const HEX = 'abcdef0123456789'

export function newId(prefix) {
  let tail = ''
  for (let i = 0; i < 10; i += 1) tail += HEX[Math.floor(Math.random() * HEX.length)]
  return `${prefix}_${tail}`
}

const NOW = () => new Date()
export const iso = (d) => d.toISOString()
export const minutesAgo = (m) => iso(new Date(NOW().getTime() - m * 60_000))
export const hoursAgo = (h) => minutesAgo(h * 60)
export const daysAgo = (d) => hoursAgo(d * 24)
export const hoursAhead = (h) => iso(new Date(NOW().getTime() + h * 3_600_000))

export const ZONES = ['Maple North', 'Maple South', 'Riverside', 'Oakwood', 'Hillcrest', 'Old Mill']

export const GROUP_SETTINGS = {
  name: 'Maple Street Mutual Aid',
  timezone: 'America/Toronto',
  quiet_hours: [21, 8],
  petty_cash_limit: 40,
  max_candidates: 3,
  escalate_hours_before_window: 6,
  confidence_threshold: 0.55,
  zones: ZONES,
}

const weekdays = (days, start, end) => days.map((weekday) => ({ weekday, start, end }))

function volunteer(id, name, zones, skills, opts = {}) {
  return {
    id,
    name,
    phone: opts.phone ?? '+1 416 555 0' + String(100 + Math.floor(Math.random() * 800)),
    email: `${name.split(' ')[0].toLowerCase()}@maplestreet.example`,
    zones,
    skills,
    availability: opts.availability ?? weekdays([0, 1, 2, 3, 4], '09:00', '17:00'),
    max_per_week: opts.max_per_week ?? 3,
    vetted: opts.vetted ?? true,
    notes: opts.notes ?? [],
    stats: {
      accepted: opts.accepted ?? 12,
      declined: opts.declined ?? 3,
      completed: opts.completed ?? 11,
      no_show: opts.no_show ?? 0,
      last_active: opts.last_active ?? daysAgo(2),
    },
    load: { this_week: opts.this_week ?? 1, max_per_week: opts.max_per_week ?? 3, last_active: opts.last_active ?? daysAgo(2) },
  }
}

export function seedVolunteers() {
  return [
    volunteer('vol_a1c3e5f709', 'Maria Okonkwo', ['Maple North', 'Riverside'], ['drive', 'lift', 'companionship'], {
      notes: ['Prefers mornings before 11.', 'Great with seniors; Mr. Okafor asks for her by name.'],
      max_per_week: 4, this_week: 3, accepted: 41, completed: 39, declined: 4, last_active: hoursAgo(5),
      availability: weekdays([0, 1, 2, 3, 4], '07:00', '12:00'),
    }),
    volunteer('vol_b2d4f6a810', 'Desmond Hale', ['Maple South', 'Old Mill'], ['drive', 'lift', 'chore'], {
      notes: ['Has a pickup truck — the person to call for furniture.'],
      max_per_week: 2, this_week: 2, accepted: 18, completed: 17, last_active: daysAgo(1),
    }),
    volunteer('vol_c3e5a7b921', 'Priya Raman', ['Riverside'], ['tech', 'translate:tamil', 'companionship'], {
      notes: ['Patient on the phone. Set up three tablets last winter.'],
      max_per_week: 3, this_week: 0, accepted: 22, completed: 21, last_active: daysAgo(4),
      availability: weekdays([1, 3, 5], '18:00', '21:00'),
    }),
    volunteer('vol_d4f6b8c032', 'Tomás Rivera', ['Maple North', 'Hillcrest'], ['cook', 'meal', 'drive'], {
      notes: ['Cooks Sunday batches; will drop off on the way home.'],
      max_per_week: 4, this_week: 1, accepted: 30, completed: 29, last_active: daysAgo(2),
    }),
    volunteer('vol_e5a7c9d143', 'Nadia Aslam', ['Oakwood'], ['groceries', 'errand', 'translate:urdu'], {
      notes: ['Shops Thursdays anyway — happy to double up.'],
      max_per_week: 3, this_week: 2, accepted: 26, completed: 25, last_active: hoursAgo(20),
    }),
    volunteer('vol_f6b8d0e254', 'Walter Kim', ['Maple South'], ['drive', 'companionship'], {
      notes: ['Retired; wide open weekday availability.'],
      max_per_week: 5, this_week: 1, accepted: 48, completed: 46, declined: 2, last_active: daysAgo(3),
      availability: weekdays([0, 1, 2, 3, 4], '08:00', '18:00'),
    }),
    volunteer('vol_a7c9e1f365', 'Grace Boateng', ['Hillcrest', 'Old Mill'], ['childcare-cleared', 'meal', 'companionship'], {
      notes: ['Cleared for childcare. Two kids of her own, unflappable.'],
      max_per_week: 2, this_week: 0, accepted: 14, completed: 14, last_active: daysAgo(6),
    }),
    volunteer('vol_b8d0f2a476', 'Jonah Feldman', ['Riverside', 'Downtown'], ['tech', 'errand'], {
      notes: ['Fastest replies in the group, usually within ten minutes.'],
      max_per_week: 3, this_week: 3, accepted: 33, completed: 30, declined: 8, last_active: hoursAgo(9),
    }),
    volunteer('vol_c9e1a3b587', 'Ruth Delacroix', ['Maple North'], ['groceries', 'cook', 'companionship'], {
      notes: ['Knows every aisle of the Fairview Metro.'],
      max_per_week: 3, this_week: 1, accepted: 19, completed: 18, last_active: daysAgo(2),
    }),
    volunteer('vol_d0f2b4c698', 'Ibrahim Sow', ['Oakwood', 'Maple South'], ['drive', 'lift', 'translate:french'], {
      notes: ['Nights only — works days at the depot.'],
      max_per_week: 2, this_week: 0, accepted: 11, completed: 11, last_active: daysAgo(8),
      availability: weekdays([0, 2, 4], '19:00', '22:00'),
    }),
    volunteer('vol_e1a3c5d709', 'Hana Sato', ['Hillcrest'], ['tech', 'errand', 'companionship'], {
      notes: ['New this spring. Keen, still learning the neighbourhood.'],
      max_per_week: 2, this_week: 1, vetted: false, accepted: 3, completed: 2, last_active: daysAgo(1),
    }),
    volunteer('vol_f2b4d6e810', 'Errol Mensah', ['Old Mill'], ['chore', 'lift', 'drive'], {
      notes: ['Shovels half the block without being asked.'],
      max_per_week: 4, this_week: 2, accepted: 37, completed: 36, last_active: hoursAgo(30),
    }),
    volunteer('vol_a3c5e7f921', 'Beatrice Lund', ['Riverside', 'Maple North'], ['meal', 'cook', 'groceries'], {
      notes: ['Bakes too much bread. This is now a community resource.'],
      max_per_week: 3, this_week: 3, accepted: 28, completed: 28, last_active: hoursAgo(14),
    }),
    volunteer('vol_b4d6f8a032', 'Samir Haddad', ['Downtown', 'Riverside'], ['drive', 'tech', 'translate:arabic'], {
      notes: ['Drives for the dialysis runs. Never late.'],
      max_per_week: 4, this_week: 2, accepted: 44, completed: 43, last_active: hoursAgo(3),
    }),
  ]
}

export function seedRequesters() {
  return [
    { id: 'rqr_1a2b3c4d5e', name: 'Amara Okafor', contact: '+1 416 555 0142', zone: 'Maple North', address: '218 Maple Ave, Apt 4', first_seen: daysAgo(210), notes: ['Dialysis Tuesdays and Fridays.', 'Prefers Maria.'], history_count: 22 },
    { id: 'rqr_2b3c4d5e6f', name: 'Sylvia Chen', contact: 'sylvia.chen@example.com', zone: 'Riverside', address: '77 River Rd', first_seen: daysAgo(120), notes: ['Lives alone; one cat, very loud.'], history_count: 9 },
    { id: 'rqr_3c4d5e6f70', name: 'Bernard Whitfield', contact: '+1 416 555 0188', zone: 'Maple South', address: '12 Larch Cres', first_seen: daysAgo(60), notes: ['Recovering from hip surgery until October.'], history_count: 5 },
    { id: 'rqr_4d5e6f7081', name: 'Fatima Nasser', contact: '+1 416 555 0173', zone: 'Oakwood', address: '340 Oakwood Blvd', first_seen: daysAgo(14), notes: ['Newer to the block. Prefers texts in the evening.'], history_count: 2 },
    { id: 'rqr_5e6f708192', name: 'Joyce Adeyemi', contact: 'joyce.a@example.com', zone: 'Hillcrest', address: '9 Hillcrest Way', first_seen: daysAgo(340), notes: ['Runs the Thursday seniors lunch.'], history_count: 31 },
    { id: 'rqr_6f70819203', name: 'Peter Nowak', contact: '+1 416 555 0119', zone: 'Old Mill', address: '55 Mill St', first_seen: daysAgo(3), notes: [], history_count: 1 },
    { id: 'rqr_708192a3b4', name: 'Doris Lam', contact: '+1 416 555 0165', zone: 'Maple North', address: '204 Maple Ave', first_seen: daysAgo(88), notes: ['Hard of hearing — text, do not call.'], history_count: 12 },
    { id: 'rqr_8192a3b4c5', name: 'Elias Mbeki', contact: 'elias.mbeki@example.com', zone: 'Riverside', address: '3 Wharf Lane', first_seen: daysAgo(45), notes: ['Works nights; sleeps mornings.'], history_count: 4 },
  ]
}

function req(id, fields) {
  return {
    id,
    source: 'sms',
    raw_text: '',
    requester_id: null,
    category: 'errand',
    summary: '',
    window_start: null,
    window_end: null,
    flexible: true,
    location_zone: null,
    constraints: [],
    urgency: 'normal',
    money_involved: false,
    safety_flags: [],
    first_time_requester: false,
    status: 'new',
    assigned_volunteer_id: null,
    attempts: [],
    created_at: hoursAgo(6),
    updated_at: hoursAgo(5),
    ...fields,
  }
}

export function seedRequests() {
  return [
    req('req_11aa22bb33', {
      source: 'sms', requester_id: 'rqr_1a2b3c4d5e', category: 'ride', urgency: 'high',
      raw_text: "Hi it's Amara — my dialysis appointment moved to 7:30 Friday morning and my son can't drive me. Is anyone free?",
      summary: 'Ride to dialysis, Friday 07:30, return around 11:00',
      window_start: hoursAhead(38), window_end: hoursAhead(42), flexible: false,
      location_zone: 'Maple North', constraints: ['wheelchair-accessible not required', 'needs return trip'],
      status: 'confirmed', assigned_volunteer_id: 'vol_a1c3e5f709',
      attempts: [{ volunteer_id: 'vol_a1c3e5f709', sent_at: hoursAgo(4), outcome: 'accepted', note: 'Happy to. I do the Friday run anyway.' }],
      created_at: hoursAgo(5), updated_at: hoursAgo(4),
    }),
    req('req_22bb33cc44', {
      source: 'form', requester_id: 'rqr_2b3c4d5e6f', category: 'groceries',
      raw_text: 'Could someone pick up milk, bread and cat food? I can pay them back.',
      summary: 'Grocery run — milk, bread, cat food',
      window_start: hoursAhead(20), window_end: hoursAhead(30),
      location_zone: 'Riverside', status: 'awaiting_reply',
      attempts: [
        { volunteer_id: 'vol_a3c5e7f921', sent_at: hoursAgo(2), outcome: 'declined', note: 'Away until Sunday.' },
        { volunteer_id: 'vol_c9e1a3b587', sent_at: minutesAgo(38), outcome: 'pending', note: null },
      ],
      created_at: hoursAgo(3), updated_at: minutesAgo(38),
    }),
    req('req_33cc44dd55', {
      source: 'voicemail', requester_id: 'rqr_3c4d5e6f70', category: 'chore',
      raw_text: "[voicemail transcript] It's Bernard on Larch. The eavestrough is full again and I still can't do ladders.",
      summary: 'Clear eavestroughs — cannot use a ladder post-surgery',
      window_start: hoursAhead(72), window_end: hoursAhead(120),
      location_zone: 'Maple South', status: 'matching',
      created_at: hoursAgo(2), updated_at: hoursAgo(1),
    }),
    req('req_44dd55ee66', {
      source: 'email', requester_id: 'rqr_4d5e6f7081', category: 'companionship', first_time_requester: true,
      raw_text: 'My mother is alone all day while I work and I wondered if someone could sit with her a couple of hours a week. She is at home in Oakwood.',
      summary: 'Weekly in-home companionship visit for requester’s mother',
      window_start: hoursAhead(96), window_end: hoursAhead(100),
      location_zone: 'Oakwood', constraints: ['in-home', 'recurring'],
      status: 'escalated',
      created_at: hoursAgo(9), updated_at: hoursAgo(8),
    }),
    req('req_55ee66ff77', {
      source: 'sms', requester_id: 'rqr_5e6f708192', category: 'meal',
      raw_text: 'Thursday lunch is 40 people this week. Any chance of two extra trays?',
      summary: 'Two extra trays for the Thursday seniors lunch',
      window_start: hoursAhead(44), window_end: hoursAhead(50),
      location_zone: 'Hillcrest', status: 'confirmed', assigned_volunteer_id: 'vol_d4f6b8c032',
      attempts: [{ volunteer_id: 'vol_d4f6b8c032', sent_at: hoursAgo(12), outcome: 'accepted', note: 'Two trays, will drop at 11.' }],
      created_at: hoursAgo(13), updated_at: hoursAgo(12),
    }),
    req('req_66ff77aa88', {
      source: 'paper', requester_id: 'rqr_6f70819203', category: 'errand', first_time_requester: true,
      raw_text: '[photo of paper slip] "Prescription pickup — Mill St pharmacy — any afternoon — P. Nowak"',
      summary: 'Prescription pickup from the Mill St pharmacy',
      window_start: hoursAhead(6), window_end: hoursAhead(10),
      location_zone: 'Old Mill', status: 'new',
      created_at: minutesAgo(24), updated_at: minutesAgo(24),
    }),
    req('req_77aa88bb99', {
      source: 'sms', requester_id: 'rqr_708192a3b4', category: 'tech',
      raw_text: 'The TV box says no signal and I text you because you said not to call. Doris.',
      summary: 'Set-top box shows "no signal" — needs a hands-on look',
      window_start: hoursAhead(28), window_end: hoursAhead(34),
      location_zone: 'Maple North', constraints: ['text only — hard of hearing'],
      status: 'in_progress', assigned_volunteer_id: 'vol_c3e5a7b921',
      attempts: [{ volunteer_id: 'vol_c3e5a7b921', sent_at: hoursAgo(26), outcome: 'accepted', note: 'I can come Wednesday evening.' }],
      created_at: hoursAgo(30), updated_at: hoursAgo(26),
    }),
    req('req_88bb99cc00', {
      source: 'email', requester_id: 'rqr_8192a3b4c5', category: 'ride',
      raw_text: 'Need a lift to the clinic on Wharf Lane, any morning next week works.',
      summary: 'Ride to the Wharf Lane clinic, flexible morning',
      window_start: hoursAhead(150), window_end: hoursAhead(156),
      location_zone: 'Riverside', status: 'completed', assigned_volunteer_id: 'vol_b4d6f8a032',
      attempts: [{ volunteer_id: 'vol_b4d6f8a032', sent_at: daysAgo(4), outcome: 'accepted', note: null }],
      created_at: daysAgo(5), updated_at: daysAgo(1),
    }),
    req('req_99cc00dd11', {
      source: 'form', requester_id: 'rqr_1a2b3c4d5e', category: 'groceries',
      raw_text: 'Same list as last week if someone is going anyway. Thank you all.',
      summary: 'Repeat grocery order — standing list',
      location_zone: 'Maple North', status: 'completed', assigned_volunteer_id: 'vol_e5a7c9d143',
      attempts: [{ volunteer_id: 'vol_e5a7c9d143', sent_at: daysAgo(3), outcome: 'accepted', note: 'Shopping Thursday anyway.' }],
      created_at: daysAgo(4), updated_at: daysAgo(2),
    }),
    req('req_00dd11ee22', {
      source: 'sms', requester_id: 'rqr_2b3c4d5e6f', category: 'chore',
      raw_text: 'Snow is up to the step again.',
      summary: 'Clear front walk and step',
      location_zone: 'Riverside', status: 'completed', assigned_volunteer_id: 'vol_f2b4d6e810',
      attempts: [{ volunteer_id: 'vol_f2b4d6e810', sent_at: daysAgo(7), outcome: 'accepted', note: null }],
      created_at: daysAgo(8), updated_at: daysAgo(6),
    }),
    req('req_aa22bb33cc', {
      source: 'sms', requester_id: 'rqr_708192a3b4', category: 'errand', money_involved: true,
      raw_text: 'My hydro bill is $140 past due and I do not get paid until the 30th. Can the group cover it?',
      summary: 'Request to cover a $140 hydro bill',
      location_zone: 'Maple North', status: 'triaging', urgency: 'high',
      created_at: minutesAgo(52), updated_at: minutesAgo(50),
    }),
    req('req_bb33cc44dd', {
      source: 'form', requester_id: 'rqr_5e6f708192', category: 'other',
      raw_text: 'We have a stack of donated coats. Someone with a car to move them to the church basement?',
      summary: 'Move donated coats to the church basement',
      window_start: hoursAhead(60), window_end: hoursAhead(70),
      location_zone: 'Hillcrest', status: 'declined',
      attempts: [
        { volunteer_id: 'vol_b2d4f6a810', sent_at: daysAgo(2), outcome: 'declined', note: 'Truck is in the shop.' },
        { volunteer_id: 'vol_f2b4d6e810', sent_at: daysAgo(2), outcome: 'timeout', note: null },
      ],
      created_at: daysAgo(3), updated_at: daysAgo(2),
    }),
  ]
}

export function seedDecisions() {
  return [
    {
      id: 'dec_safe01a2b3',
      request_id: 'req_44dd55ee66',
      kind: 'safety',
      title: 'A neighbour reports a child home alone with the stove on',
      context:
        "A message arrived from **Fatima Nasser** (Oakwood, first-time requester) at 6:12pm:\n\n" +
        '"my neighbours kid is home alone and I can smell the stove from the hall, nobody answers the door"\n\n' +
        'Porchlight **stopped** before contacting any volunteer. The safety policy denies autonomous outreach on danger language:\n\n' +
        '- child unattended\n' +
        '- possible fire hazard\n' +
        '- no responsible adult reachable\n\n' +
        'A reply draft is queued that tells Fatima to call **911** first. It has not been sent.',
      recommendation:
        'Send the emergency-services reply now and call Fatima yourself. This is not a volunteer dispatch.',
      options: [
        { id: 'i_will_handle', label: 'I’ll handle it', description: 'Send the 911 reply and mark this for the coordinator.' },
        { id: 'approve', label: 'Send reply, keep watching', description: 'Send the drafted reply and keep the request open.' },
        { id: 'decline_request', label: 'Close — not for us', description: 'Close the request with a note. No volunteer is contacted.' },
      ],
      interrupt_id: 'int_safe01a2b3',
      session_id: 'req_44dd55ee66',
      node: 'intake',
      status: 'open',
      resolved_option: null,
      resolved_note: null,
      created_at: minutesAgo(18),
      resolved_at: null,
    },
    {
      id: 'dec_money4c5d6',
      request_id: 'req_aa22bb33cc',
      kind: 'money',
      title: 'Doris Lam asks the group to cover a $140 hydro bill',
      context:
        'Doris has asked twelve times before — always groceries or a ride, never money. This is her first financial request.\n\n' +
        '- Amount: **$140.00**\n' +
        '- Petty-cash limit: **$40.00**\n' +
        '- Disconnection notice date: **the 21st**\n\n' +
        'Porchlight has *not* promised anything to Doris and has *not* asked any volunteer for money. ' +
        'The money policy requires you before any commitment.',
      recommendation:
        'Refer her to the city utility-arrears program (she qualifies on history) and offer a grocery run this week so the money goes to the bill.',
      options: [
        { id: 'approve', label: 'Approve from petty cash', description: 'Over the $40 limit — records an exception in the log.' },
        { id: 'i_will_handle', label: 'I’ll call her', description: 'Coordinator takes it; Porchlight stops here.' },
        { id: 'decline_request', label: 'Refer, don’t fund', description: 'Send the arrears-program referral and offer groceries instead.' },
      ],
      interrupt_id: 'int_money4c5d6',
      session_id: 'req_aa22bb33cc',
      node: 'intake',
      status: 'open',
      resolved_option: null,
      resolved_note: null,
      created_at: minutesAgo(46),
      resolved_at: null,
    },
    {
      id: 'dec_unmatch789',
      request_id: 'req_bb33cc44dd',
      kind: 'unmatched',
      title: 'No one free to move the donated coats',
      context: 'Three asks, no acceptance, and the window closes tomorrow.',
      recommendation: 'Widen the pool to Downtown volunteers.',
      options: [
        { id: 'widen_pool', label: 'Widen the pool', description: 'Include neighbouring zones.' },
        { id: 'reschedule', label: 'Reschedule', description: 'Push the window out a week.' },
      ],
      interrupt_id: 'int_unmatch789',
      session_id: 'req_bb33cc44dd',
      node: 'outreach',
      status: 'resolved',
      resolved_option: 'reschedule',
      resolved_note: 'Church basement is free next Saturday anyway.',
      created_at: daysAgo(2),
      resolved_at: daysAgo(2),
    },
  ]
}

function log(agent, kind, summary, detail, opts = {}) {
  return {
    id: newId('log'),
    ts: opts.ts ?? minutesAgo(Math.floor(Math.random() * 600)),
    request_id: opts.request_id ?? null,
    agent,
    kind,
    summary,
    detail,
    autonomous: opts.autonomous ?? true,
  }
}

export function seedLog() {
  const rows = [
    log('intake', 'tool_call', 'Read Amara Okafor’s history — 22 past requests, dialysis Tuesdays and Fridays', { tool: 'lookup_requester_history', contact: '+1 416 555 0142', matched: 'rqr_1a2b3c4d5e' }, { request_id: 'req_11aa22bb33', ts: hoursAgo(5) }),
    log('intake', 'model', 'Parsed the text into a ride request, Friday 07:30, return trip needed', { model: 'claude-haiku-4-5', tokens_in: 812, tokens_out: 190 }, { request_id: 'req_11aa22bb33', ts: hoursAgo(5) }),
    log('matcher', 'tool_call', 'Ranked 3 candidates; Maria Okonkwo first (0.91) — same zone, mornings, asked for by name', { tool: 'find_candidates', top: ['vol_a1c3e5f709', 'vol_b4d6f8a032', 'vol_f6b8d0e254'], confidence: 0.91 }, { request_id: 'req_11aa22bb33', ts: hoursAgo(5) }),
    log('matcher', 'memory', 'Recalled: "Mr. Okafor prefers Maria" from the March run', { query: 'Okafor preferences', hits: 2 }, { request_id: 'req_11aa22bb33', ts: hoursAgo(5) }),
    log('outreach', 'message_sent', 'Asked Maria Okonkwo — personal note, no address until she accepts', { to: 'volunteer', recipient_id: 'vol_a1c3e5f709', redacted: ['address'] }, { request_id: 'req_11aa22bb33', ts: hoursAgo(5) }),
    log('outreach', 'tool_call', 'Maria accepted in 9 minutes', { tool: 'read_replies', intent: 'accept', confidence: 0.97 }, { request_id: 'req_11aa22bb33', ts: hoursAgo(4) }),
    log('outreach', 'tool_call', 'Assigned Maria Okonkwo and released the pickup address', { tool: 'assign_volunteer', volunteer_id: 'vol_a1c3e5f709' }, { request_id: 'req_11aa22bb33', ts: hoursAgo(4) }),
    log('steward', 'message_sent', 'Confirmed with Amara: "Maria will be at your door 07:10 Friday."', { to: 'requester', recipient_id: 'rqr_1a2b3c4d5e' }, { request_id: 'req_11aa22bb33', ts: hoursAgo(4) }),
    log('steward', 'tool_call', 'Scheduled a reminder for Thursday 19:00', { tool: 'schedule_message', send_at: hoursAhead(24) }, { request_id: 'req_11aa22bb33', ts: hoursAgo(4) }),
    log('steward', 'memory', 'Remembered: Amara’s dialysis moved to Friday mornings', { about_id: 'rqr_1a2b3c4d5e', kind: 'fact' }, { request_id: 'req_11aa22bb33', ts: hoursAgo(4) }),

    log('intake', 'model', 'Parsed Sylvia Chen’s form into a grocery run', { model: 'claude-haiku-4-5' }, { request_id: 'req_22bb33cc44', ts: hoursAgo(3) }),
    log('matcher', 'tool_call', 'Beatrice Lund is at 3 of 3 this week — skipped for fairness', { tool: 'volunteer_load', volunteer_id: 'vol_a3c5e7f921', this_week: 3, max_per_week: 3 }, { request_id: 'req_22bb33cc44', ts: hoursAgo(3) }),
    log('outreach', 'message_sent', 'Asked Beatrice Lund anyway as second choice — she declined, away until Sunday', { to: 'volunteer', recipient_id: 'vol_a3c5e7f921' }, { request_id: 'req_22bb33cc44', ts: hoursAgo(2) }),
    log('outreach', 'message_sent', 'Asked Ruth Delacroix — awaiting reply', { to: 'volunteer', recipient_id: 'vol_c9e1a3b587' }, { request_id: 'req_22bb33cc44', ts: minutesAgo(38) }),

    log('intake', 'tool_call', 'Transcribed Bernard’s voicemail and matched him to an existing requester', { tool: 'lookup_requester_history', matched: 'rqr_3c4d5e6f70' }, { request_id: 'req_33cc44dd55', ts: hoursAgo(2) }),
    log('matcher', 'model', 'Confidence 0.74 — Errol Mensah and Desmond Hale both fit', { model: 'claude-sonnet-4-6', confidence: 0.74 }, { request_id: 'req_33cc44dd55', ts: hoursAgo(1) }),

    log('intake', 'policy', 'Danger language detected — autonomous outreach denied, card raised', { rule: 'safety.child_unattended', action: 'Deny' }, { request_id: 'req_44dd55ee66', autonomous: false, ts: minutesAgo(18) }),
    log('intake', 'decision', 'Raised a red card: child home alone, stove on', { decision_id: 'dec_safe01a2b3', kind: 'safety' }, { request_id: 'req_44dd55ee66', autonomous: false, ts: minutesAgo(18) }),

    log('intake', 'policy', 'Money request over the $40 petty-cash limit — held for the coordinator', { rule: 'money.over_limit', amount: 140, limit: 40, action: 'Confirm' }, { request_id: 'req_aa22bb33cc', autonomous: false, ts: minutesAgo(46) }),
    log('intake', 'decision', 'Raised an amber card: $140 hydro bill', { decision_id: 'dec_money4c5d6', kind: 'money' }, { request_id: 'req_aa22bb33cc', autonomous: false, ts: minutesAgo(46) }),

    log('outreach', 'message_sent', 'Asked Tomás Rivera for two trays — accepted the same hour', { to: 'volunteer', recipient_id: 'vol_d4f6b8c032' }, { request_id: 'req_55ee66ff77', ts: hoursAgo(12) }),
    log('steward', 'message_sent', 'Confirmed with Joyce: two trays at 11:00 Thursday', { to: 'requester', recipient_id: 'rqr_5e6f708192' }, { request_id: 'req_55ee66ff77', ts: hoursAgo(12) }),
    log('steward', 'memory', 'Remembered: Thursday lunch is running at 40 covers, up from 28', { about_id: 'rqr_5e6f708192' }, { request_id: 'req_55ee66ff77', ts: hoursAgo(12) }),

    log('intake', 'model', 'Read the photographed paper slip — prescription pickup, Mill St', { model: 'claude-haiku-4-5', multimodal: true }, { request_id: 'req_66ff77aa88', ts: minutesAgo(24) }),
    log('matcher', 'tool_call', 'Only Errol Mensah covers Old Mill this week', { tool: 'find_candidates', confidence: 0.62 }, { request_id: 'req_66ff77aa88', ts: minutesAgo(22) }),

    log('outreach', 'policy', 'Held a message until 08:00 — quiet hours', { rule: 'quiet_hours', action: 'Guide', send_at: '08:00' }, { request_id: 'req_77aa88bb99', ts: hoursAgo(26) }),
    log('steward', 'tool_call', 'Closed the Wharf Lane ride — completed, no follow-up needed', { tool: 'close_request', outcome: 'completed' }, { request_id: 'req_88bb99cc00', ts: daysAgo(1) }),
    log('steward', 'memory', 'Remembered: Samir Haddad is reliable for clinic runs (43 completed)', { about_id: 'vol_b4d6f8a032' }, { request_id: 'req_88bb99cc00', ts: daysAgo(1) }),
    log('steward', 'message_sent', 'Post-visit check-in with Sylvia — walk is clear, no issues', { to: 'requester', recipient_id: 'rqr_2b3c4d5e6f' }, { request_id: 'req_00dd11ee22', ts: daysAgo(6) }),
    log('outreach', 'policy', 'Redacted Doris Lam’s address from an unvetted volunteer’s message', { rule: 'redact.address', action: 'Transform', volunteer_id: 'vol_e1a3c5d709' }, { request_id: 'req_77aa88bb99', ts: hoursAgo(27) }),
    log('brief', 'model', 'Nightly digest written — rides up 3x on last month', { model: 'claude-sonnet-4-6' }, { ts: hoursAgo(11) }),
  ]
  return rows.sort((a, b) => (a.ts < b.ts ? 1 : -1))
}

export function seedMessages() {
  return [
    { id: newId('msg'), request_id: 'req_11aa22bb33', to: 'volunteer', recipient_id: 'vol_a1c3e5f709', channel: 'sms', body: 'Morning Maria — Amara’s dialysis moved to Friday 07:30 and she needs a ride there and back. You did the March run. Any chance? No pressure, I’ll ask Walter next.', scheduled_for: null, sent_at: hoursAgo(5), status: 'delivered' },
    { id: newId('msg'), request_id: 'req_11aa22bb33', to: 'requester', recipient_id: 'rqr_1a2b3c4d5e', channel: 'sms', body: 'Hi Amara — Maria Okonkwo will pick you up at 07:10 on Friday and wait for the return. She has your number if anything changes.', scheduled_for: null, sent_at: hoursAgo(4), status: 'delivered' },
    { id: newId('msg'), request_id: 'req_11aa22bb33', to: 'volunteer', recipient_id: 'vol_a1c3e5f709', channel: 'sms', body: 'Reminder: Amara pickup tomorrow 07:10, 218 Maple Ave Apt 4.', scheduled_for: hoursAhead(24), sent_at: null, status: 'scheduled' },
    { id: newId('msg'), request_id: 'req_22bb33cc44', to: 'volunteer', recipient_id: 'vol_a3c5e7f921', channel: 'sms', body: 'Beatrice — small grocery run in Riverside (milk, bread, cat food). Are you around this week?', scheduled_for: null, sent_at: hoursAgo(2), status: 'delivered' },
    { id: newId('msg'), request_id: 'req_22bb33cc44', to: 'volunteer', recipient_id: 'vol_c9e1a3b587', channel: 'sms', body: 'Ruth — could you add a small Riverside order to your shop? Milk, bread, cat food. I’ll send the address if you can.', scheduled_for: null, sent_at: minutesAgo(38), status: 'sent' },
    { id: newId('msg'), request_id: 'req_55ee66ff77', to: 'volunteer', recipient_id: 'vol_d4f6b8c032', channel: 'sms', body: 'Tomás — Thursday lunch is at 40 covers. Two extra trays possible?', scheduled_for: null, sent_at: hoursAgo(12), status: 'delivered' },
  ]
}

export const SAMPLES = [
  { id: 'smp_01', label: 'Ride to dialysis', expected: 'quiet', source: 'sms', text: "It's Amara — my dialysis moved to Friday 7:30am and my son can't drive me. Anyone free?" },
  { id: 'smp_02', label: 'Small grocery run', expected: 'quiet', source: 'form', text: 'Could someone grab milk, bread and cat food for me this week? Riverside, no rush.' },
  { id: 'smp_03', label: 'Snow on the step', expected: 'quiet', source: 'sms', text: 'Snow is up to the step again and I still cannot shovel. 12 Larch Cres.' },
  { id: 'smp_04', label: 'Meal train, new baby', expected: 'quiet', source: 'form', text: 'The Ferreiras had their baby Tuesday. Can we get three meals to them next week?' },
  { id: 'smp_05', label: 'TV box, no signal', expected: 'quiet', source: 'sms', text: 'The TV box says no signal. Please text, do not call. Doris.' },
  { id: 'smp_06', label: 'Prescription pickup (paper slip)', expected: 'quiet', source: 'paper', text: 'Prescription pickup — Mill St pharmacy — any afternoon — P. Nowak' },
  { id: 'smp_07', label: 'Lift to the clinic', expected: 'quiet', source: 'email', text: 'Need a lift to the Wharf Lane clinic, any morning next week works for me.' },
  { id: 'smp_08', label: 'Move donated coats', expected: 'quiet', source: 'form', text: 'We have a stack of donated coats. Someone with a car to move them to the church basement?' },
  { id: 'smp_09', label: 'Dog walk while in hospital', expected: 'quiet', source: 'sms', text: 'In hospital until Thursday. Is anyone able to walk Biscuit twice a day? Neighbour has a key.' },
  { id: 'smp_10', label: 'Translate a letter', expected: 'quiet', source: 'email', text: 'I received a letter from the city in English and I need help understanding it. I speak Tamil.' },
  { id: 'smp_11', label: 'Airport run, flexible', expected: 'quiet', source: 'sms', text: 'Flight lands 9pm Sunday at the island airport. Any chance of a lift home to Oakwood?' },
  { id: 'smp_12', label: 'Lawn is knee high', expected: 'quiet', source: 'voicemail', text: '[voicemail] The lawn is knee high and the city sent a letter. I cannot push the mower any more.' },
  { id: 'smp_13', label: 'Weekly seniors lunch help', expected: 'quiet', source: 'form', text: 'Thursday lunch is 40 people this week. Any chance of two extra trays?' },
  { id: 'smp_14', label: 'Furniture move', expected: 'quiet', source: 'sms', text: 'Got a free couch off the curb but cannot lift it. Anyone with a truck around Old Mill?' },
  { id: 'smp_15', label: 'Company after a funeral', expected: 'quiet', source: 'email', text: 'My husband died in June and the evenings are very long. Could someone visit sometimes?' },
  { id: 'smp_16', label: 'Child home alone, stove on', expected: 'card', source: 'sms', text: "my neighbours kid is home alone and I can smell the stove from the hall, nobody answers the door" },
  { id: 'smp_17', label: 'Chest pain', expected: 'card', source: 'voicemail', text: '[voicemail] I have had chest pain since this morning and I did not want to bother the hospital. Could someone come by?' },
  { id: 'smp_18', label: 'Hydro bill past due', expected: 'card', source: 'sms', text: 'My hydro bill is $140 past due and I do not get paid until the 30th. Can the group cover it?' },
  { id: 'smp_19', label: 'Gift card request', expected: 'card', source: 'email', text: 'Would the group be able to send a $75 grocery gift card? Things are tight this month.' },
  { id: 'smp_20', label: 'Cash for a taxi', expected: 'card', source: 'sms', text: 'I need money for a taxi to the hospital tomorrow, about $60 each way.' },
  { id: 'smp_21', label: 'New requester, in-home help', expected: 'card', source: 'email', text: 'My mother is alone all day while I work. Could someone sit with her at home a few hours a week?' },
  { id: 'smp_22', label: 'Volunteer raises a concern', expected: 'card', source: 'sms', text: 'I did the drop-off but something felt off at that address and I would rather not go back alone.' },
  { id: 'smp_23', label: 'Threat in the message', expected: 'card', source: 'sms', text: 'My roommate has been threatening me and I need to get my things out of the apartment tonight.' },
  { id: 'smp_24', label: 'Nobody free, window tomorrow', expected: 'card', source: 'form', text: 'Surgery is tomorrow at 6am and I still have no ride. I have asked everyone I know.' },
]
