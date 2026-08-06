import { useState, useEffect, useRef } from 'react'
import Head from 'next/head'

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

interface Appointment {
  patient_id: string
  name: string
  dob: string
  department: string
  appointment_doctor: string
  appointment_date: string
  appointment_time: string
  payer: string
  copay: string
  payment_status: string
  payment_date: string
  reason: string
  created_at: string
  appointment_status: string
}

interface Slot {
  doctor: string
  date: string
  time: string
}

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

function PayNowButton({ apt }: { apt: Appointment }) {
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
        const res = await fetch(`${API}/portal/payment-status/${apt.patient_id}`)
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
    setLoading(true)
    setError('')
    // Pre-open a blank tab synchronously (before any await) so the
    // browser doesn't block it as a popup once the real URL is ready.
    const tab = window.open('', '_blank')
    try {
      const res = await fetch(`${API}/portal/create-payment-link`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ patient_id: apt.patient_id }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        setError(body.detail || 'Could not start payment.')
        tab?.close()
        return
      }
      const data = await res.json()
      if (tab) {
        tab.location.href = data.url
      } else {
        window.open(data.url, '_blank')
      }
      startPolling()
    } catch {
      setError('Could not reach the server.')
      tab?.close()
    } finally {
      setLoading(false)
    }
  }

  if (paid) return (
    <div style={{ background: '#e0f0ea', borderRadius: 8, padding: '10px 14px', fontSize: 13, color: '#0d6b52', marginTop: 12 }}>
      ✓ Payment received — thank you!
    </div>
  )

  return (
    <div style={{ marginTop: 14 }}>
      <button onClick={handlePay} disabled={loading} style={{
        padding: '8px 18px', borderRadius: 8,
        background: 'transparent', border: '0.5px solid #0d6b52',
        color: '#0d6b52', fontSize: 13, cursor: loading ? 'not-allowed' : 'pointer', fontFamily: 'inherit',
      }}>
        {loading ? 'Opening secure payment...' : 'Pay now'}
      </button>
      {polling && (
        <div style={{ fontSize: 12, color: '#8a8880', marginTop: 8 }}>
          Waiting for payment to complete in the other tab...
        </div>
      )}
      {error && <div style={{ fontSize: 12, color: '#c04020', marginTop: 8 }}>{error}</div>}
    </div>
  )
}

function RescheduleSlots({ apt, onDone, onCancel }: {
  apt: Appointment; onDone: () => void; onCancel: () => void
}) {
  const [slots, setSlots] = useState<Slot[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [confirming, setConfirming] = useState<Slot | null>(null)
  const [dayFilter, setDayFilter] = useState('')
  const [timeFilter, setTimeFilter] = useState('')
  const [sameReason, setSameReason] = useState(true)
  const [newReason, setNewReason] = useState('')

  const loadSlots = () => {
    setLoading(true)
    setError('')
    const params = new URLSearchParams({ department: apt.department })
    if (dayFilter) params.set('day', dayFilter)
    if (timeFilter === 'morning') params.set('before_time', '12:00 PM')
    if (timeFilter === 'afternoon') { params.set('after_time', '12:00 PM'); params.set('before_time', '5:00 PM') }
    if (timeFilter === 'evening') params.set('after_time', '5:00 PM')

    fetch(`${API}/portal/reschedule-slots?${params.toString()}`)
      .then(r => r.json())
      .then(d => setSlots((d.slots || []).slice(0, 5)))
      .catch(() => setError('Could not load available times.'))
      .finally(() => setLoading(false))
  }

  useEffect(() => { loadSlots() }, [dayFilter, timeFilter])

  const confirmReschedule = async (slot: Slot) => {
    setConfirming(slot)
    try {
      await fetch(`${API}/portal/reschedule-appointment`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          patient_id: apt.patient_id,
          doctor: slot.doctor,
          date: slot.date,
          time: slot.time,
          reason: sameReason ? null : newReason,
        }),
      })
      onDone()
    } catch {
      setError('Could not reschedule — please try again.')
      setConfirming(null)
    }
  }

  return (
    <div style={{ marginTop: 14, borderTop: '0.5px solid #e2ddd6', paddingTop: 14 }}>
      <div style={{ fontSize: 12, color: '#8a8880', marginBottom: 10 }}>
        Rescheduling within {apt.department}
      </div>

      <div style={{ marginBottom: 14 }}>
        <label style={{ fontSize: 12, color: '#4a4845', display: 'block', marginBottom: 6 }}>
          Reason for visit
        </label>
        <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
          <button onClick={() => setSameReason(true)} style={{
            flex: 1, padding: '8px', borderRadius: 8, fontSize: 12, cursor: 'pointer', fontFamily: 'inherit',
            border: sameReason ? '1.5px solid #0d6b52' : '1px solid #e2ddd6',
            background: sameReason ? '#e0f0ea' : '#fafaf8', color: '#1a1916',
          }}>Same as before</button>
          <button onClick={() => setSameReason(false)} style={{
            flex: 1, padding: '8px', borderRadius: 8, fontSize: 12, cursor: 'pointer', fontFamily: 'inherit',
            border: !sameReason ? '1.5px solid #0d6b52' : '1px solid #e2ddd6',
            background: !sameReason ? '#e0f0ea' : '#fafaf8', color: '#1a1916',
          }}>Something's changed</button>
        </div>
        {apt.reason && sameReason && (
          <div style={{ fontSize: 12, color: '#aaa' }}>Current: {apt.reason}</div>
        )}
        {!sameReason && (
          <input
            value={newReason}
            onChange={e => setNewReason(e.target.value)}
            placeholder="What's changed, or anything to add?"
            style={{
              width: '100%', padding: '9px 12px', borderRadius: 8, border: '1px solid #e2ddd6',
              fontSize: 13, fontFamily: 'inherit', outline: 'none', boxSizing: 'border-box',
            }}
          />
        )}
      </div>

      <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        <select value={dayFilter} onChange={e => setDayFilter(e.target.value)} style={{
          flex: 1, padding: '8px 10px', borderRadius: 8, border: '1px solid #e2ddd6',
          fontSize: 12, fontFamily: 'inherit', background: '#fafaf8', color: '#1a1916',
        }}>
          {DAY_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
        <select value={timeFilter} onChange={e => setTimeFilter(e.target.value)} style={{
          flex: 1, padding: '8px 10px', borderRadius: 8, border: '1px solid #e2ddd6',
          fontSize: 12, fontFamily: 'inherit', background: '#fafaf8', color: '#1a1916',
        }}>
          {TIME_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
      </div>

      {loading && <div style={{ fontSize: 13, color: '#8a8880' }}>Loading available times...</div>}
      {error && <div style={{ fontSize: 12, color: '#c04020', marginBottom: 8 }}>{error}</div>}
      {!loading && slots.length === 0 && !error && (
        <div style={{ fontSize: 13, color: '#8a8880' }}>No available slots match — try a different day or time.</div>
      )}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {slots.map((s, i) => (
          <button
            key={i}
            onClick={() => confirmReschedule(s)}
            disabled={!!confirming || (!sameReason && !newReason.trim())}
            style={{
              textAlign: 'left', padding: '9px 14px', borderRadius: 8,
              border: '1px solid #e2ddd6',
              background: confirming === s ? '#e0f0ea' : '#fafaf8',
              color: '#1a1916', fontSize: 13,
              cursor: (confirming || (!sameReason && !newReason.trim())) ? 'not-allowed' : 'pointer',
              fontFamily: 'inherit',
            }}
          >
            {s.doctor} — {s.date} at {s.time}
          </button>
        ))}
      </div>
      <button onClick={onCancel} style={{
        marginTop: 10, fontSize: 12, color: '#8a8880', background: 'none',
        border: 'none', cursor: 'pointer', fontFamily: 'inherit',
      }}>Never mind</button>
    </div>
  )
}

function AppointmentCard({ apt, onChanged }: { apt: Appointment; onChanged: () => void }) {
  const [showReschedule, setShowReschedule] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const [cancelError, setCancelError] = useState('')
  const paid = apt.payment_status === 'paid'
  const cancelled = apt.appointment_status === 'cancelled'

  const handleCancel = async () => {
    if (!window.confirm(`Cancel your appointment with ${apt.appointment_doctor} on ${apt.appointment_date}?`)) return
    setCancelling(true)
    setCancelError('')
    try {
      const res = await fetch(`${API}/portal/cancel-appointment`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ patient_id: apt.patient_id }),
      })
      if (!res.ok) {
        setCancelError(`Could not cancel (server said: ${res.status}).`)
        return
      }
      onChanged()
    } catch {
      setCancelError('Could not reach the server.')
    } finally {
      setCancelling(false)
    }
  }

  return (
    <div style={{
      background: '#fff', border: '0.5px solid #e2ddd6',
      borderRadius: 12, padding: '18px 22px', marginBottom: 12,
      opacity: cancelled ? 0.6 : 1,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <div style={{ fontSize: 15, fontWeight: 600, color: '#1a1916', marginBottom: 4 }}>
            {apt.appointment_doctor}
            {cancelled && (
              <span style={{ fontSize: 11, color: '#c04020', marginLeft: 8, fontWeight: 500 }}>Cancelled</span>
            )}
          </div>
          <div style={{ fontSize: 13, color: '#8a8880' }}>
            {apt.appointment_date} · {apt.appointment_time} · {apt.department}
          </div>
          {apt.reason && (
            <div style={{ fontSize: 12, color: '#aaa', marginTop: 4 }}>Reason: {apt.reason}</div>
          )}
        </div>
        <div style={{ textAlign: 'right', flexShrink: 0, marginLeft: 16 }}>
          <div style={{
            fontSize: 11, padding: '3px 10px', borderRadius: 20,
            background: paid ? '#e0f0ea' : '#fdf0dc',
            color: paid ? '#0d6b52' : '#b06a10', marginBottom: 4,
          }}>
            {paid ? 'Paid ✓' : 'Unpaid'}
          </div>
          {apt.copay && apt.copay !== '0' && (
            <div style={{ fontSize: 13, color: '#4a4845' }}>Copay: ${apt.copay}</div>
          )}
          <div style={{ fontSize: 11, color: '#ccc', marginTop: 2 }}>{apt.payer}</div>
        </div>
      </div>

      {!cancelled && !paid && apt.copay && parseFloat(apt.copay) > 0 && (
        <PayNowButton apt={apt} />
      )}

      {!cancelled && !showReschedule && (
        <div style={{ marginTop: 14 }}>
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={() => setShowReschedule(true)} style={{
              padding: '8px 18px', borderRadius: 8,
              background: 'transparent', border: '0.5px solid #8a8880',
              color: '#4a4845', fontSize: 13, cursor: 'pointer', fontFamily: 'inherit',
            }}>Reschedule</button>
            <button onClick={handleCancel} disabled={cancelling} style={{
              padding: '8px 18px', borderRadius: 8,
              background: 'transparent', border: '0.5px solid #c04020',
              color: '#c04020', fontSize: 13,
              cursor: cancelling ? 'not-allowed' : 'pointer', fontFamily: 'inherit',
            }}>{cancelling ? 'Cancelling...' : 'Cancel appointment'}</button>
          </div>
          {cancelError && <div style={{ fontSize: 12, color: '#c04020', marginTop: 8 }}>{cancelError}</div>}
        </div>
      )}

      {showReschedule && (
        <RescheduleSlots
          apt={apt}
          onDone={() => { setShowReschedule(false); onChanged() }}
          onCancel={() => setShowReschedule(false)}
        />
      )}
    </div>
  )
}

type Step = 'identify' | 'enter-code' | 'verified'

export default function PortalPage() {
  const [step, setStep] = useState<Step>('identify')
  const [name, setName] = useState('')
  const [dob, setDob] = useState('')
  const [lookupKey, setLookupKey] = useState('')
  const [sentTo, setSentTo] = useState('')
  const [code, setCode] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [appointments, setAppointments] = useState<Appointment[]>([])

  const handleIdentify = async () => {
    if (!name || !dob) return
    setLoading(true)
    setError('')
    try {
      const lookupRes = await fetch(`${API}/portal/lookup`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, dob }),
      })
      if (!lookupRes.ok) {
        setError('No records found. Check your name and date of birth.')
        return
      }
      await requestCode()
    } catch {
      setError('Could not connect to server.')
    } finally {
      setLoading(false)
    }
  }

  const requestCode = async () => {
    setLoading(true)
    setError('')
    try {
      const res = await fetch(`${API}/portal/request-code`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, dob, method: 'email' }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        setError(body.detail || 'Could not send code.')
        return
      }
      const data = await res.json()
      setLookupKey(data.lookup_key)
      setSentTo(data.sent_to)
      setStep('enter-code')
    } catch {
      setError('Could not reach the server.')
    } finally {
      setLoading(false)
    }
  }

  const verifyCode = async () => {
    if (!code) return
    setLoading(true)
    setError('')
    try {
      const res = await fetch(`${API}/portal/verify-code`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ lookup_key: lookupKey, code }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        setError(body.detail || 'Incorrect code.')
        return
      }
      const data = await res.json()
      setAppointments(data.patients)
      setStep('verified')
    } catch {
      setError('Could not reach the server.')
    } finally {
      setLoading(false)
    }
  }

  const refresh = async () => {
    const res = await fetch(`${API}/portal/lookup`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, dob }),
    })
    if (res.ok) {
      const data = await res.json()
      setAppointments(data.patients)
    }
  }

  const totalUnpaid = appointments
    .filter(a => a.appointment_status !== 'cancelled' && a.payment_status !== 'paid' && a.copay && parseFloat(a.copay) > 0)
    .reduce((sum, a) => sum + parseFloat(a.copay), 0)

  return (
    <>
      <Head>
        <title>Patient Portal — Ledelsea</title>
        <link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,wght@0,300;0,400;1,300;1,400&family=Instrument+Sans:wght@400;500;600&display=swap" rel="stylesheet" />
      </Head>

      <div style={{ minHeight: '100vh', background: '#f8f6f1', fontFamily: "'Instrument Sans', sans-serif" }}>
        <div style={{
          background: '#1a1916', padding: '16px 32px',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
            <a href="/" style={{ color: 'rgba(255,255,255,0.4)', fontSize: 13, textDecoration: 'none' }}>
              ← Lea Medical Center
            </a>
            <div style={{ color: 'rgba(255,255,255,0.15)', fontSize: 13 }}>|</div>
            <div style={{ fontFamily: "'Fraunces', serif", fontSize: 18, color: '#fff', fontWeight: 300 }}>
              Patient <em style={{ color: '#9fb8ac', fontStyle: 'italic' }}>Portal</em>
            </div>
          </div>
          <div style={{ fontSize: 11, color: '#8a8880' }}>Ledelsea · Secure · HIPAA compliant</div>
        </div>

        <div style={{ maxWidth: 480, margin: '0 auto', padding: '40px 24px' }}>

          {step === 'identify' && (
            <div style={{ background: '#fff', borderRadius: 16, border: '0.5px solid #e2ddd6', padding: '36px 32px' }}>
              <div style={{ fontSize: 22, fontWeight: 600, color: '#1a1916', marginBottom: 6 }}>Access your visit</div>
              <div style={{ fontSize: 14, color: '#8a8880', marginBottom: 28 }}>
                Enter your name and date of birth. We'll email you a quick verification code.
              </div>
              <div style={{ marginBottom: 16 }}>
                <label style={{ fontSize: 12, color: '#4a4845', display: 'block', marginBottom: 6 }}>Full name</label>
                <input value={name} onChange={e => setName(e.target.value)} placeholder="e.g. Brandon Collins"
                  style={{ width: '100%', padding: '11px 14px', borderRadius: 8, border: '1px solid #e2ddd6', fontSize: 14, fontFamily: 'inherit', outline: 'none', boxSizing: 'border-box' }} />
              </div>
              <div style={{ marginBottom: 24 }}>
                <label style={{ fontSize: 12, color: '#4a4845', display: 'block', marginBottom: 6 }}>Date of birth</label>
                <input value={dob} onChange={e => setDob(e.target.value)} placeholder="MM/DD/YYYY"
                  style={{ width: '100%', padding: '11px 14px', borderRadius: 8, border: '1px solid #e2ddd6', fontSize: 14, fontFamily: 'inherit', outline: 'none', boxSizing: 'border-box' }} />
              </div>
              {error && <div style={{ fontSize: 13, color: '#c04020', marginBottom: 14 }}>{error}</div>}
              <button onClick={handleIdentify} disabled={loading || !name || !dob} style={{
                width: '100%', padding: '12px', borderRadius: 8,
                background: loading || !name || !dob ? '#e2ddd6' : '#0d6b52',
                border: 'none', color: '#fff', fontSize: 14, fontWeight: 500,
                cursor: loading || !name || !dob ? 'not-allowed' : 'pointer', fontFamily: 'inherit',
              }}>{loading ? 'Checking...' : 'Continue'}</button>
            </div>
          )}

          {step === 'enter-code' && (
            <div style={{ background: '#fff', borderRadius: 16, border: '0.5px solid #e2ddd6', padding: '36px 32px' }}>
              <div style={{ fontSize: 20, fontWeight: 600, color: '#1a1916', marginBottom: 6 }}>Enter your code</div>
              <div style={{ fontSize: 14, color: '#8a8880', marginBottom: 24 }}>
                We sent a code to {sentTo}.
              </div>
              <input
                value={code}
                onChange={e => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                placeholder="6-digit code"
                inputMode="numeric"
                style={{
                  width: '100%', padding: '13px 14px', borderRadius: 8, border: '1.5px solid #0d6b52',
                  fontSize: 20, letterSpacing: '0.3em', textAlign: 'center', fontFamily: 'inherit',
                  outline: 'none', boxSizing: 'border-box', marginBottom: 16,
                }}
              />
              {error && <div style={{ fontSize: 13, color: '#c04020', marginBottom: 14 }}>{error}</div>}
              <button onClick={verifyCode} disabled={loading || code.length !== 6} style={{
                width: '100%', padding: '12px', borderRadius: 8,
                background: loading || code.length !== 6 ? '#e2ddd6' : '#0d6b52',
                border: 'none', color: '#fff', fontSize: 14, fontWeight: 500,
                cursor: loading || code.length !== 6 ? 'not-allowed' : 'pointer', fontFamily: 'inherit',
              }}>{loading ? 'Verifying...' : 'Verify'}</button>
              <button onClick={requestCode} disabled={loading} style={{ marginTop: 12, fontSize: 12, color: '#8a8880', background: 'none', border: 'none', cursor: loading ? 'not-allowed' : 'pointer', fontFamily: 'inherit', display: 'block', width: '100%', textAlign: 'center' }}>
                Didn't get it? Send again
              </button>
            </div>
          )}

          {step === 'verified' && (
            <>
              <div style={{ marginBottom: 24 }}>
                <div style={{ fontSize: 22, fontWeight: 600, color: '#1a1916' }}>{appointments[0]?.name}</div>
                <div style={{ fontSize: 13, color: '#8a8880', marginTop: 4 }}>
                  DOB: {dob} · {appointments.length} appointment{appointments.length !== 1 ? 's' : ''}
                </div>
              </div>

              {totalUnpaid > 0 && (
                <div style={{
                  background: '#fdf0dc', border: '0.5px solid #f0c878', borderRadius: 12,
                  padding: '14px 20px', marginBottom: 20, display: 'flex',
                  justifyContent: 'space-between', alignItems: 'center',
                }}>
                  <div style={{ fontSize: 13, fontWeight: 500, color: '#b06a10' }}>Outstanding balance</div>
                  <div style={{ fontSize: 22, fontWeight: 600, color: '#b06a10' }}>${totalUnpaid.toFixed(2)}</div>
                </div>
              )}
              {totalUnpaid === 0 && (
                <div style={{ background: '#e0f0ea', border: '0.5px solid #9fd8c0', borderRadius: 12, padding: '14px 20px', marginBottom: 20, fontSize: 13, color: '#0d6b52' }}>
                  ✓ All balances paid — you're up to date
                </div>
              )}

              {appointments.map(apt => (
                <AppointmentCard key={apt.patient_id} apt={apt} onChanged={refresh} />
              ))}

              <button onClick={() => { setStep('identify'); setAppointments([]); setName(''); setDob(''); setCode('') }} style={{
                marginTop: 8, fontSize: 13, color: '#8a8880', background: 'none', border: 'none', cursor: 'pointer', fontFamily: 'inherit',
              }}>← Sign out</button>
            </>
          )}
        </div>
      </div>
    </>
  )
}