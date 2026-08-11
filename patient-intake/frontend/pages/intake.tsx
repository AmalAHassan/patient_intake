import { useState, useEffect, useRef, useCallback } from 'react'
import Head from 'next/head'

interface Message {
  role: 'bot' | 'user' | 'error' | 'system'
  text: string
}

interface IntakeData {
  name: string
  dob: string
  phone: string
  email: string
  address: string
  insurance_id: string
  payer: string
  copay: string
  department: string
  reason: string
  appointment_doctor: string
  appointment_date: string
  appointment_time: string
  guardian_name: string
  guardian_relationship: string
}

type Status = 'collecting' | 'complete' | 'emergency_redirect' | 'staff_requested' | 'ended'

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

const STEPS = [
  { id: 1, label: 'Name & DOB',        tag: 'Start'    },
  { id: 2, label: 'Identity check',    tag: 'Verify'   },
  { id: 3, label: 'Confirm details',   tag: 'Review'   },
  { id: 4, label: 'Insurance',         tag: 'Coverage' },
  { id: 5, label: 'Department',        tag: 'Route'    },
  { id: 6, label: 'Reason for visit',  tag: 'Note'     },
  { id: 7, label: 'Scheduling',        tag: 'Book'     },
  { id: 8, label: 'Confirmed',         tag: 'Done'     },
]

const DAY_OPTIONS = [
  { value: '', label: 'Any day' },
  { value: 'monday', label: 'Monday' },
  { value: 'tuesday', label: 'Tuesday' },
  { value: 'wednesday', label: 'Wednesday' },
  { value: 'thursday', label: 'Thursday' },
  { value: 'friday', label: 'Friday' },
]

const TIME_OPTIONS = [
  { value: '', label: 'Any time' },
  { value: 'morning', label: 'Morning' },
  { value: 'afternoon', label: 'Afternoon' },
  { value: 'evening', label: 'Evening' },
]

function inferStep(messages: Message[]): number {
  const bot = messages.filter(m => m.role === 'bot').map(m => m.text.toLowerCase()).join(' ')
  if (bot.includes("you're all set") || bot.includes('confirmed'))                   return 8
  if (bot.includes('available appointment') || bot.includes('dr.'))                  return 7
  if (bot.includes('coming in today') || bot.includes('why you'))                    return 6
  if (bot.includes('department') || bot.includes('family medicine'))                 return 5
  if (bot.includes('insurance') || bot.includes('copay'))                            return 4
  if (bot.includes('phone') && bot.includes('still correct'))                        return 3
  if (bot.includes('date of birth') || bot.includes('found a record'))               return 2
  return 1
}

/**
 * Defensive layout fix applied to EVERY bot message the moment it
 * enters state (see addMessage below) — regardless of which backend
 * endpoint produced it (intake/start, intake/message, intake/quick-slots
 * all funnel through here). The backend agents present numbered lists
 * (departments, appointment slots) and are instructed to always put
 * each item on its own line, but the model periodically glues the FIRST
 * item onto the same line as the question that precedes it, e.g.
 * "Which department are you visiting today? 1. Family Medicine\n2.
 * OB/GYN...". cleanBotMessage and getQuickReplies below only recognize
 * a line as a selectable option if the line itself STARTS with a
 * number, so a glued item 1 silently stays as plain unclickable text
 * while items 2+ correctly become buttons — a real but easy-to-miss
 * feature bug, since the message still reads fine to a human. Rather
 * than rely on the backend to always format this perfectly, normalize
 * it here too: insert the missing line break whenever a numbered item
 * ("1. ", "2. ", etc.) appears anywhere other than the start of a line.
 */
function normalizeNumberedList(text: string): string {
  if (!text) return text
  return text.replace(/([^\n])[ \t]+(\d{1,2}\.\s)/g, '$1\n$2')
}

function cleanBotMessage(text: string): string {
  return text
    .split('\n')
    .filter(line => !/^\d+\./.test(line.trim()))
    .join('\n')
    .replace(/\s*Here are your options:\s*/gi, '')
    .replace(/\s*Which one works best for you\?\s*$/gi, '')
    .trim()
}

function formatDob(value: string): string {
  const digits = value.replace(/\D/g, '').slice(0, 8)
  if (digits.length <= 2) return digits
  if (digits.length <= 4) return `${digits.slice(0, 2)}/${digits.slice(2)}`
  return `${digits.slice(0, 2)}/${digits.slice(2, 4)}/${digits.slice(4)}`
}

function getQuickReplies(lastBotMsg: string): string[] {
  const msg = lastBotMsg.toLowerCase()
  if (msg.includes('is that still correct') || msg.includes('still current') ||
      msg.includes('still your current') || msg.includes('has that changed') ||
      msg.includes('is that right') || msg.includes('still active') ||
      msg.includes('ending in') || msg.includes('is that still') ||
      msg.includes('sound good'))
    return ['Yes', 'No, it changed']
  const numberedLines = lastBotMsg.split('\n').filter(l => /^\d+\./.test(l.trim()))
  if (numberedLines.length > 0) {
    return numberedLines.map(l => l.trim())
  }
  if (msg.includes('which department are you visiting'))
    return [
      '1. Family Medicine', '2. OB/GYN', '3. Cardiology', '4. Urgent Care',
      '5. Mental Health', '6. Dermatology', '7. Pediatrics', '8. Other',
    ]
  return []
}

function QuickReplies({ replies, onSelect }: { replies: string[]; onSelect: (r: string) => void }) {
  if (replies.length === 0) return null
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, padding: '2px 0 6px', justifyContent: 'flex-start' }}>
      {replies.map(r => (
        <button key={r} onClick={() => onSelect(r)} style={{
          padding: '6px 14px', borderRadius: 20,
          border: '1.5px solid #8b5e52',
          background: 'transparent', color: '#8b5e52',
          fontSize: 13, cursor: 'pointer', fontFamily: 'inherit',
          transition: 'all 0.15s', whiteSpace: 'nowrap',
          letterSpacing: '0.01em',
        }}
          onMouseEnter={e => {
            (e.target as HTMLButtonElement).style.background = '#8b5e52'
            ;(e.target as HTMLButtonElement).style.color = '#fff'
          }}
          onMouseLeave={e => {
            (e.target as HTMLButtonElement).style.background = 'transparent'
            ;(e.target as HTMLButtonElement).style.color = '#8b5e52'
          }}
        >{r}</button>
      ))}
    </div>
  )
}

function QuickSlotFilter({ sessionId, onResult }: { sessionId: string; onResult: (reply: string) => void }) {
  const [day, setDay] = useState('')
  const [timeOfDay, setTimeOfDay] = useState('')
  const [loading, setLoading] = useState(false)

  const fetchSlots = async () => {
    setLoading(true)
    try {
      const body: any = { session_id: sessionId }
      if (day) body.day = day
      if (timeOfDay === 'morning') body.before_time = '12:00 PM'
      if (timeOfDay === 'afternoon') { body.after_time = '12:00 PM'; body.before_time = '5:00 PM' }
      if (timeOfDay === 'evening') body.after_time = '5:00 PM'

      const res = await fetch(`${API}/intake/quick-slots`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const data = await res.json()
      onResult(data.reply || 'Could not load slots right now.')
    } catch {
      onResult('Could not load slots right now.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, padding: '2px 0 6px' }}>
      <select value={day} onChange={e => setDay(e.target.value)} style={{
        padding: '6px 10px', borderRadius: 20, border: '1.5px solid #8b5e52',
        fontSize: 12, fontFamily: 'inherit', background: 'transparent', color: '#8b5e52',
      }}>
        {DAY_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
      <select value={timeOfDay} onChange={e => setTimeOfDay(e.target.value)} style={{
        padding: '6px 10px', borderRadius: 20, border: '1.5px solid #8b5e52',
        fontSize: 12, fontFamily: 'inherit', background: 'transparent', color: '#8b5e52',
      }}>
        {TIME_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
      <button onClick={fetchSlots} disabled={loading} style={{
        padding: '6px 14px', borderRadius: 20, border: '1.5px solid #8b5e52',
        background: '#8b5e52', color: '#fff', fontSize: 12,
        cursor: loading ? 'not-allowed' : 'pointer', fontFamily: 'inherit',
      }}>{loading ? '...' : 'Quick search'}</button>
    </div>
  )
}

function ConsentForm({ patientName, onSigned }: { patientName: string; onSigned: (sig: string) => void }) {
  const [selected, setSelected] = useState<number | null>(null)
  const [custom, setCustom] = useState('')
  const [signed, setSigned] = useState(false)

  const suggestions = [
    { font: "'Dancing Script', cursive" },
    { font: "'Pacifico', cursive" },
    { font: "'Great Vibes', cursive" },
  ]

  const finalSig = selected !== null ? patientName : custom
  const selectedFont = selected !== null ? suggestions[selected].font : 'inherit'

  const handleSign = () => {
    if (!finalSig.trim()) return
    setSigned(true)
    onSigned(finalSig)
  }

  if (signed) return (
    <div style={{
      background: '#f5efe8', border: '1px solid #d4c4bc',
      borderRadius: 16, padding: '14px 18px', maxWidth: 360,
      alignSelf: 'flex-start', marginTop: 4, flexShrink: 0,
    }}>
      <div style={{ fontSize: 13, color: '#6b3d30', fontWeight: 500 }}>Consent signed</div>
      <div style={{ fontSize: 11, color: '#9e8880', marginTop: 5 }}>
        Signed as: <em style={{ fontFamily: selectedFont, fontSize: 17, color: '#2c1a14' }}>{finalSig}</em>
      </div>
      <div style={{ fontSize: 11, color: '#9e8880', marginTop: 2 }}>
        {new Date().toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' })}
      </div>
    </div>
  )

  return (
    <>
      <link href="https://fonts.googleapis.com/css2?family=Dancing+Script:wght@600&family=Pacifico&family=Great+Vibes&display=swap" rel="stylesheet" />
      <div style={{
        background: '#fff', border: '1px solid #e8ddd6',
        borderRadius: 16, padding: '18px 20px', maxWidth: 360,
        alignSelf: 'flex-start', marginTop: 4, flexShrink: 0,
        boxShadow: '0 1px 4px rgba(44,26,20,0.06)',
      }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: '#2c1a14', marginBottom: 4 }}>HIPAA Consent</div>
        <div style={{ fontSize: 11, color: '#9e8880', lineHeight: 1.6, marginBottom: 14, padding: '8px 10px', background: '#faf7f3', borderRadius: 8 }}>
          I authorize Ledelsea Health to use and disclose my protected health information for treatment, payment, and healthcare operations as described in the Notice of Privacy Practices.
        </div>
        <div style={{ fontSize: 11, color: '#6b3d30', marginBottom: 8, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Choose a signature</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 12 }}>
          {suggestions.map((s, i) => (
            <button key={i} onClick={() => { setSelected(i); setCustom('') }} style={{
              padding: '8px 14px', borderRadius: 8, textAlign: 'left',
              border: selected === i ? '1.5px solid #8b5e52' : '1px solid #e8ddd6',
              background: selected === i ? '#faf0ec' : '#faf7f3',
              cursor: 'pointer', fontFamily: s.font, fontSize: 22,
              color: '#2c1a14', transition: 'all 0.15s',
            }}>{patientName}</button>
          ))}
        </div>
        <div style={{ fontSize: 11, color: '#9e8880', marginBottom: 5 }}>Or type your own</div>
        <input
          value={custom}
          onChange={e => { setCustom(e.target.value); setSelected(null) }}
          placeholder="Your full name"
          style={{
            width: '100%', padding: '9px 12px', borderRadius: 8,
            border: custom ? '1.5px solid #8b5e52' : '1px solid #e8ddd6',
            fontSize: 14, fontFamily: 'inherit', outline: 'none',
            boxSizing: 'border-box', marginBottom: 12, background: '#faf7f3',
          }}
        />
        {finalSig.trim() && (
          <div style={{ marginBottom: 12, padding: '8px 12px', background: '#faf7f3', borderRadius: 8 }}>
            <div style={{ fontSize: 10, color: '#9e8880', marginBottom: 3, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Preview</div>
            <div style={{ fontFamily: selectedFont, fontSize: selected !== null ? 24 : 15, color: '#2c1a14' }}>{finalSig}</div>
          </div>
        )}
        <button onClick={handleSign} disabled={!finalSig.trim()} style={{
          width: '100%', padding: '9px', borderRadius: 8,
          background: !finalSig.trim() ? '#d4c4bc' : '#8b5e52',
          border: 'none', color: '#fff', fontSize: 13, fontWeight: 600,
          cursor: !finalSig.trim() ? 'not-allowed' : 'pointer', fontFamily: 'inherit',
          letterSpacing: '0.02em',
        }}>I agree &amp; sign</button>
        <div style={{ fontSize: 10, color: '#c4a89e', textAlign: 'center', marginTop: 6 }}>
          By signing you agree to the HIPAA consent above
        </div>
      </div>
    </>
  )
}

// Pay Now half of the payment action — unchanged behavior (real tab,
// real polling), but now reports upward via onStart the MOMENT the
// patient commits to this path, so the sibling Pay Later button can
// hide itself rather than sitting there as a conflicting option once
// a real payment attempt is underway.
function IntakePayNowButton({ sessionId, onStart }: { sessionId: string; onStart: () => void }) {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [polling, setPolling] = useState(false)
  const [paid, setPaid] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [])

  const startPolling = () => {
    setPolling(true)
    const startTime = Date.now()
    pollRef.current = setInterval(async () => {
      try {
        const res = await fetch(`${API}/payment/status-by-session/${sessionId}`)
        const data = await res.json()
        if (data.paid) {
          if (pollRef.current) clearInterval(pollRef.current)
          setPolling(false)
          setPaid(true)
          return
        }
      } catch {
        // network hiccup — just try again next tick
      }
      if (Date.now() - startTime >= 5 * 60 * 1000) {
        if (pollRef.current) clearInterval(pollRef.current)
        setPolling(false)
      }
    }, 4000)
  }

  const handlePay = async () => {
    onStart()
    setLoading(true)
    setError('')
    // Pre-open synchronously, before any await — browsers block
    // window.open() calls that happen after an async gap.
    const tab = window.open('', '_blank')
    try {
      const res = await fetch(`${API}/intake/create-payment-link`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        setError(body.detail || 'Could not start payment.')
        tab?.close()
        return
      }
      const data = await res.json()
      if (tab) tab.location.href = data.url
      else window.open(data.url, '_blank')
      startPolling()
    } catch {
      setError('Could not reach the server.')
      tab?.close()
    } finally {
      setLoading(false)
    }
  }

  if (paid) return (
    <div style={{ background: '#e0f0ea', borderRadius: 8, padding: '10px 14px', fontSize: 13, color: '#0d6b52' }}>
      ✓ Payment received — thank you!
    </div>
  )

  return (
    <div>
      <button onClick={handlePay} disabled={loading} style={{
        padding: '9px 20px', borderRadius: 8,
        background: loading ? '#e8ddd6' : '#8b5e52',
        border: 'none', color: '#fff', fontSize: 13, fontWeight: 600,
        cursor: loading ? 'not-allowed' : 'pointer', fontFamily: 'inherit',
      }}>
        {loading ? 'Opening secure payment...' : 'Pay now'}
      </button>
      {polling && (
        <div style={{ fontSize: 12, color: '#9e8880', marginTop: 8 }}>
          Waiting for payment to complete in the other tab...
        </div>
      )}
      {error && <div style={{ fontSize: 12, color: '#b04030', marginTop: 8 }}>{error}</div>}
    </div>
  )
}

const PAY_LATER_COUNTDOWN_SECONDS = 10

// The one card shown after intake completes when a copay is due — two
// real choices, not two suggestions: Pay Now hands off to Stripe with
// no AI in the trigger path (see IntakePayNowButton); Pay Later commits
// to ending the session outright rather than leaving it in limbo, with
// a visible countdown before the automatic restart so the choice feels
// deliberate rather than abrupt.
function PaymentAction({ sessionId, onSessionEnd }: { sessionId: string; onSessionEnd: () => void }) {
  const [payNowStarted, setPayNowStarted] = useState(false)
  const [payLaterChosen, setPayLaterChosen] = useState(false)
  const [secondsLeft, setSecondsLeft] = useState(PAY_LATER_COUNTDOWN_SECONDS)

  useEffect(() => {
    if (!payLaterChosen) return
    if (secondsLeft <= 0) {
      onSessionEnd()
      return
    }
    const timer = setTimeout(() => setSecondsLeft(s => s - 1), 1000)
    return () => clearTimeout(timer)
  }, [payLaterChosen, secondsLeft, onSessionEnd])

  if (payLaterChosen) {
    return (
      <div style={{
        background: '#fdf4e8', border: '1px solid #e8c878',
        borderRadius: 16, padding: '14px 20px',
        maxWidth: 360, width: '100%', alignSelf: 'flex-start', marginTop: 4,
        flexShrink: 0,
      }}>
        <div style={{ fontSize: 13, color: '#8b6020', fontWeight: 600 }}>Session ended</div>
        <div style={{ fontSize: 12, color: '#8b6020', marginTop: 4 }}>
          You can pay at the clinic or through the patient portal. Redirecting to start a new intake in {secondsLeft} second{secondsLeft !== 1 ? 's' : ''}...
        </div>
      </div>
    )
  }

  return (
    <div style={{
      background: '#fff', border: '1px solid #e8ddd6',
      borderRadius: 16, padding: '14px 20px',
      maxWidth: 360, width: '100%', alignSelf: 'flex-start', marginTop: 4,
      flexShrink: 0,
      boxShadow: '0 2px 8px rgba(44,26,20,0.06)',
    }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
        <IntakePayNowButton sessionId={sessionId} onStart={() => setPayNowStarted(true)} />
        {!payNowStarted && (
          <button onClick={() => setPayLaterChosen(true)} style={{
            padding: '9px 20px', borderRadius: 8,
            background: 'transparent', border: '1.5px solid #8b5e52',
            color: '#8b5e52', fontSize: 13, fontWeight: 600,
            cursor: 'pointer', fontFamily: 'inherit',
          }}>
            Pay later
          </button>
        )}
      </div>
    </div>
  )
}

export default function IntakePage() {
  const [sessionId, setSessionId]           = useState<string | null>(null)
  const [messages, setMessages]             = useState<Message[]>([])
  const [input, setInput]                   = useState('')
  const [loading, setLoading]               = useState(false)
  const [status, setStatus]                 = useState<Status>('collecting')
  const [currentAgent, setCurrentAgent]     = useState<string>('')
  const [intakeData, setIntakeData]         = useState<IntakeData | null>(null)
  const [patientId, setPatientId]           = useState<string | null>(null)
  const [currentStep, setCurrentStep]       = useState(1)
  const [quickReplyUsed, setQuickReplyUsed] = useState(false)
  const [consentSigned, setConsentSigned]   = useState(false)
  const messagesEndRef                      = useRef<HTMLDivElement>(null)
  const inputRef                            = useRef<HTMLInputElement>(null)
  const bootedRef                           = useRef(false)

  const scroll = () => messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  useEffect(() => { scroll() }, [messages, loading, consentSigned])

  const addMessage = (role: Message['role'], text: string) => {
    const normalized = role === 'bot' ? normalizeNumberedList(text) : text
    setMessages(prev => {
      const next = [...prev, { role, text: normalized }]
      setCurrentStep(inferStep(next))
      return next
    })
    if (role === 'bot') setQuickReplyUsed(false)
  }

  const boot = useCallback(async () => {
    setLoading(true)
    try {
      const res  = await fetch(`${API}/intake/start`, { method: 'POST' })
      const data = await res.json()
      setSessionId(data.session_id)
      addMessage('bot', data.message || "Hi, welcome! What's your full name?")
    } catch {
      addMessage('error', "Can't reach the backend. Make sure uvicorn is running on port 8000.")
    } finally {
      setLoading(false)
      inputRef.current?.focus()
    }
  }, [])

  useEffect(() => {
    if (bootedRef.current) return
    bootedRef.current = true
    boot()
  }, [boot])

  const sendText = async (text: string) => {
    if (!text || !sessionId || status !== 'collecting' || loading) return
    addMessage('user', text)
    setInput('')
    setLoading(true)
    try {
      const res = await fetch(`${API}/intake/message`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, message: text }),
      })
      const data = await res.json()
      const clean = (s: string) => (s || '').replace(/\*\*(.+?)\*\*/g, '$1')
      const rawReply = clean(data.reply)

      if (data.current_agent) setCurrentAgent(data.current_agent)

      if (data.status === 'complete') {
        addMessage('bot', rawReply)
        setStatus('complete')
        if (data.data) setIntakeData(data.data)
        if (data.patient_id) setPatientId(data.patient_id)
      } else if (data.status === 'emergency_redirect') {
        addMessage('error', rawReply)
        setStatus('emergency_redirect')
        setCurrentStep(8)
      } else if (data.status === 'staff_requested') {
        addMessage('bot', rawReply)
        setStatus('staff_requested')
      } else if (data.status === 'ended') {
        setStatus('ended')
      } else {
        addMessage('bot', rawReply || 'Something went wrong.')
      }
    } catch {
      addMessage('error', 'Error reaching the server.')
    } finally {
      setLoading(false)
      inputRef.current?.focus()
    }
  }

  const handleSend = () => sendText(input.trim())

  const handleQuickReply = (reply: string) => {
    const toSend = reply.replace(/^\d+\.\s*/, '')
    setQuickReplyUsed(true)
    sendText(toSend)
  }

  const restart = () => {
    setSessionId(null); setMessages([]); setInput('')
    setStatus('collecting'); setIntakeData(null); setPatientId(null)
    setCurrentStep(1); setCurrentAgent('')
    setQuickReplyUsed(false); setConsentSigned(false)
    bootedRef.current = false
    boot()
  }

  const lastBotMsg = [...messages].reverse().find(m => m.role === 'bot')?.text || ''
  const quickReplies = status === 'collecting' && !loading && !quickReplyUsed
    ? getQuickReplies(lastBotMsg) : []

  const isDobQuestion = status === 'collecting' && !loading &&
    (lastBotMsg.toLowerCase().includes('date of birth') ||
     lastBotMsg.toLowerCase().includes('mm/dd/yyyy')) &&
    !lastBotMsg.toLowerCase().includes('insurance') &&
    !lastBotMsg.toLowerCase().includes('phone') &&
    !lastBotMsg.toLowerCase().includes('email') &&
    !lastBotMsg.toLowerCase().includes('confirm') &&
    !lastBotMsg.toLowerCase().includes('details')

  // The scheduling agent always uses this exact phrasing when confirming
  // a specific chosen slot (see SCHEDULING_PROMPT) — hide the quick-slot
  // dropdown at that point, since offering to search for MORE slots
  // makes no sense while the patient is just answering yes/no to confirm
  // the one they already picked.
  const isConfirmingSlot = lastBotMsg.toLowerCase().includes('shall i book that')

  const locked = status !== 'collecting'
  const placeholderText = locked
    ? status === 'emergency_redirect' ? 'Please call 911 or 988 immediately.'
    : status === 'complete'           ? 'Intake complete — tap New intake to start again.'
    : 'Session ended.'
    : isDobQuestion                   ? 'MM / DD / YYYY'
    : quickReplies.length > 0         ? 'Or type your response...'
    : 'Type a message...'

  const isMinor = !!(intakeData?.guardian_name && intakeData.guardian_name.trim())
  const showConsent = status === 'complete' && intakeData && isMinor && !consentSigned
  const showPaymentAction = status === 'complete' && intakeData && sessionId
    && intakeData.copay && parseFloat(intakeData.copay) > 0

  const showQuickSlotFilter = currentAgent === 'scheduling' && status === 'collecting' && !loading && !isConfirmingSlot

  return (
    <>
      <Head>
        <title>Patient Intake — Ledelsea</title>
        <link href="https://fonts.googleapis.com/css2?family=Barlow:wght@400;500;600;700&family=Barlow+Condensed:wght@500;600;700&display=swap" rel="stylesheet" />
      </Head>

      <style>{`
        * { box-sizing: border-box; }
        body { margin: 0; background: #f5efe8; }
        ::-webkit-scrollbar { width: 4px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: #d4c4bc; border-radius: 4px; }
        @keyframes bounce { 0%,60%,100% { transform: translateY(0) } 30% { transform: translateY(-4px) } }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(6px) } to { opacity: 1; transform: translateY(0) } }
        @media (max-width: 768px) {
          .sidebar { display: none !important; }
        }
      `}</style>

      <div style={{ display: 'flex', height: '100vh', overflow: 'hidden', fontFamily: "'Barlow', sans-serif", background: '#f5efe8' }}>

        <aside className="sidebar" style={{
          width: 240, background: '#2c1a14', display: 'flex', flexDirection: 'column',
          padding: '28px 20px 24px', flexShrink: 0, overflowY: 'auto',
        }}>
          <div style={{ marginBottom: 32, display: 'flex', alignItems: 'center', gap: 10 }}>
            <svg width="28" height="32" viewBox="0 0 28 32" fill="none">
              <path d="M14 2L14 18M14 18L6 26M14 18L22 26M14 26L14 30M10 30L18 30" stroke="#c4a49a" strokeWidth="2" strokeLinecap="round"/>
              <circle cx="14" cy="6" r="3" fill="#8b5e52"/>
            </svg>
            <div>
              <div style={{ fontFamily: "'Barlow Condensed', sans-serif", fontSize: 17, color: '#fff', fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', lineHeight: 1 }}>Ledelsea</div>
              <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.35)', letterSpacing: '0.08em', textTransform: 'uppercase', marginTop: 2 }}>Patient Intake</div>
            </div>
          </div>

          <div style={{ fontSize: 9, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'rgba(255,255,255,0.3)', marginBottom: 10 }}>Progress</div>
          <nav style={{ display: 'flex', flexDirection: 'column', gap: 1, flex: 1 }}>
            {STEPS.map(step => {
              const isDone = step.id < currentStep
              const isActive = step.id === currentStep
              return (
                <div key={step.id} style={{
                  display: 'flex', alignItems: 'center', gap: 10,
                  padding: '8px 10px', borderRadius: 8,
                  background: isActive ? 'rgba(139,94,82,0.2)' : 'transparent',
                  transition: 'background 0.2s',
                }}>
                  <div style={{
                    width: 20, height: 20, borderRadius: '50%', flexShrink: 0,
                    border: `1.5px solid ${isDone ? '#8b5e52' : isActive ? '#c4a49a' : 'rgba(255,255,255,0.15)'}`,
                    background: isDone ? '#8b5e52' : 'transparent',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                  }}>
                    {isDone && <svg width="8" height="7" viewBox="0 0 10 8" fill="none"><path d="M1 4L3.5 6.5L9 1" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>}
                  </div>
                  <span style={{ fontSize: 12, flex: 1, color: isActive ? '#fff' : isDone ? 'rgba(255,255,255,0.5)' : 'rgba(255,255,255,0.25)', fontWeight: isActive ? 600 : 400 }}>
                    {step.label}
                  </span>
                  {(isDone || isActive) && (
                    <span style={{
                      fontSize: 9, padding: '1px 6px', borderRadius: 20, flexShrink: 0,
                      background: isDone ? 'rgba(139,94,82,0.3)' : 'rgba(196,164,154,0.2)',
                      color: isDone ? '#c4a49a' : 'rgba(255,255,255,0.4)',
                      letterSpacing: '0.04em',
                    }}>
                      {isDone ? 'Done' : step.tag}
                    </span>
                  )}
                </div>
              )
            })}
          </nav>

          <a href="/portal" style={{
            display: 'block', marginTop: 16, padding: '9px 10px',
            borderRadius: 8, border: '1px solid rgba(255,255,255,0.1)',
            fontSize: 11, color: 'rgba(255,255,255,0.4)', textDecoration: 'none',
            textAlign: 'center', letterSpacing: '0.02em',
          }}>
            View statements & pay →
          </a>

          <div style={{ marginTop: 16, paddingTop: 16, borderTop: '1px solid rgba(255,255,255,0.06)', fontSize: 10, color: 'rgba(255,255,255,0.2)', lineHeight: 1.7, letterSpacing: '0.02em' }}>
            HAPI FHIR · NIST IAL2<br />HIPAA compliant
          </div>
        </aside>

        <main style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', background: '#f5efe8' }}>
          <div style={{
            padding: '14px 24px', background: '#fff',
            borderBottom: '1px solid #e8ddd6',
            display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexShrink: 0,
          }}>
            <div>
              <div style={{ fontSize: 13, fontWeight: 700, color: '#2c1a14', letterSpacing: '0.01em' }}>Patient Registration</div>
              <div style={{ fontSize: 11, color: '#9e8880', marginTop: 1 }}>Powered by Ledelsea · Secure · HIPAA compliant</div>
            </div>
            <button onClick={restart} style={{
              fontSize: 11, color: '#6b4a40', background: 'none',
              border: '1px solid #e8ddd6', borderRadius: 8,
              padding: '5px 12px', cursor: 'pointer', fontFamily: 'inherit',
              fontWeight: 500, letterSpacing: '0.02em',
            }}>Start over</button>
          </div>

          <div style={{
            flex: 1, overflowY: 'auto', padding: '20px 24px',
            display: 'flex', flexDirection: 'column', gap: 6,
          }}>
            {messages.map((msg, i) => {
              const cleaned = msg.role === 'bot' ? cleanBotMessage(msg.text) : msg.text
              return <Bubble key={i} msg={{ ...msg, text: cleaned }} />
            })}
            {loading && <TypingIndicator />}

            {quickReplies.length > 0 && (
              <div style={{ marginTop: 2 }}>
                <QuickReplies replies={quickReplies} onSelect={handleQuickReply} />
              </div>
            )}

            {showQuickSlotFilter && sessionId && (
              <div style={{ marginTop: 2 }}>
                <QuickSlotFilter sessionId={sessionId} onResult={(reply) => addMessage('bot', reply)} />
              </div>
            )}

            {showPaymentAction && sessionId && (
              <PaymentAction sessionId={sessionId} onSessionEnd={restart} />
            )}

            {status === 'complete' && intakeData && showConsent && (
              <ConsentForm
                patientName={intakeData.guardian_name || intakeData.name}
                onSigned={(sig) => {
                  setConsentSigned(true)
                  console.log(`[consent] Signed as: ${sig} at ${new Date().toISOString()}`)
                }}
              />
            )}

            {consentSigned && (
              <div style={{
                background: '#f5ede6', border: '1px solid #d4c4bc',
                borderRadius: 12, padding: '10px 14px', fontSize: 12,
                color: '#6b3d30', maxWidth: 360, alignSelf: 'flex-start', flexShrink: 0,
              }}>
                Consent received. Your registration is complete — see you at your appointment.
              </div>
            )}

            {status === 'staff_requested' && (
              <div style={{
                background: '#fdf4e8', border: '1px solid #e8c878',
                borderRadius: 12, padding: '10px 14px', fontSize: 12,
                color: '#8b6020', alignSelf: 'center', textAlign: 'center', maxWidth: '80%',
              }}>
                Please call the clinic directly to complete your registration.
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>

          <div style={{
            padding: '12px 24px 14px', background: '#fff',
            borderTop: '1px solid #e8ddd6', flexShrink: 0,
          }}>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <input
                ref={inputRef}
                value={input}
                onChange={e => {
                  if (isDobQuestion) setInput(formatDob(e.target.value))
                  else setInput(e.target.value)
                }}
                onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() } }}
                placeholder={placeholderText}
                disabled={locked || loading}
                inputMode={isDobQuestion ? 'numeric' : 'text'}
                style={{
                  flex: 1, padding: '10px 16px',
                  border: isDobQuestion ? '1.5px solid #8b5e52' : '1.5px solid #e8ddd6',
                  borderRadius: 24, fontSize: 14, outline: 'none', fontFamily: 'inherit',
                  background: locked ? '#f5efe8' : '#fff', color: '#2c1a14',
                  letterSpacing: isDobQuestion ? '0.08em' : 'normal',
                  transition: 'border-color 0.15s',
                }}
              />
              <button
                onClick={handleSend}
                disabled={locked || loading || !input.trim()}
                style={{
                  width: 40, height: 40, borderRadius: '50%', flexShrink: 0,
                  background: locked || !input.trim() ? '#e8ddd6' : '#8b5e52',
                  border: 'none', cursor: locked || !input.trim() ? 'not-allowed' : 'pointer',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  transition: 'background 0.15s',
                }}
              >
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="22" y1="2" x2="11" y2="13" />
                  <polygon points="22 2 15 22 11 13 2 9 22 2" />
                </svg>
              </button>
            </div>
          </div>
        </main>
      </div>
    </>
  )
}

function Bubble({ msg }: { msg: Message }) {
  const isUser  = msg.role === 'user'
  const isError = msg.role === 'error'

  if (isError) return (
    <div style={{
      background: '#fdeee8', border: '1px solid #e8b4a0',
      borderRadius: 12, padding: '10px 14px',
      fontSize: 13, color: '#b04030', lineHeight: 1.55,
      maxWidth: '80%', alignSelf: 'center', textAlign: 'center',
      animation: 'fadeIn 0.2s ease',
    }}>{msg.text}</div>
  )

  return (
    <div style={{
      maxWidth: '72%',
      alignSelf: isUser ? 'flex-end' : 'flex-start',
      animation: 'fadeIn 0.2s ease',
    }}>
      <div style={{
        padding: '10px 14px',
        borderRadius: isUser ? '18px 18px 4px 18px' : '18px 18px 18px 4px',
        background: isUser ? '#8b5e52' : '#fff',
        border: isUser ? 'none' : '1px solid #e8ddd6',
        fontSize: 14, lineHeight: 1.5,
        color: isUser ? '#fff' : '#2c1a14',
        whiteSpace: 'pre-wrap', wordBreak: 'break-word',
        boxShadow: isUser ? 'none' : '0 1px 2px rgba(44,26,20,0.04)',
      }}>{msg.text}</div>
    </div>
  )
}

function TypingIndicator() {
  return (
    <div style={{ alignSelf: 'flex-start', animation: 'fadeIn 0.2s ease' }}>
      <div style={{
        display: 'flex', gap: 4, padding: '10px 14px',
        background: '#fff', border: '1px solid #e8ddd6',
        borderRadius: '18px 18px 18px 4px',
        boxShadow: '0 1px 2px rgba(44,26,20,0.04)',
      }}>
        {[0, 1, 2].map(i => (
          <div key={i} style={{
            width: 6, height: 6, borderRadius: '50%', background: '#c4a49a',
            animation: `bounce 1.2s ${i * 0.2}s infinite ease-in-out`,
          }} />
        ))}
      </div>
    </div>
  )
}