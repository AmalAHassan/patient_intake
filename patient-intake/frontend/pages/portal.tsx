import { useState, useEffect } from 'react'
import Head from 'next/head'
import { loadStripe } from '@stripe/stripe-js'
import { Elements, CardElement, useStripe, useElements } from '@stripe/react-stripe-js'

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
  appointment_status: string // "confirmed" | "cancelled"
}

interface Slot {
  doctor: string
  date: string
  time: string
}

function PaymentForm({ appointment, onPaid }: { appointment: Appointment; onPaid: () => void }) {
  const stripe = useStripe()
  const elements = useElements()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState(false)

  const handlePay = async () => {
    if (!stripe || !elements) return
    setLoading(true)
    setError('')
    try {
      const res = await fetch(`${API}/payment/create-intent`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          patient_id: appointment.patient_id,
          amount_dollars: parseFloat(appointment.copay),
          patient_name: appointment.name,
          description: `Copay — ${appointment.appointment_doctor} ${appointment.appointment_date}`,
        }),
      })
      const { client_secret, payment_intent_id } = await res.json()
      const card = elements.getElement(CardElement)
      if (!card) return
      const result = await stripe.confirmCardPayment(client_secret, {
        payment_method: { card },
      })
      if (result.error) {
        setError(result.error.message || 'Payment failed')
      } else if (result.paymentIntent?.status === 'succeeded') {
        await fetch(`${API}/payment/confirm`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            patient_id: appointment.patient_id,
            payment_intent_id,
          }),
        })
        setSuccess(true)
        onPaid()
      }
    } catch (e: any) {
      setError(e.message || 'Something went wrong')
    } finally {
      setLoading(false)
    }
  }

  if (success) return (
    <div style={{ background: '#e0f0ea', borderRadius: 8, padding: '12px 16px', fontSize: 13, color: '#0d6b52', marginTop: 12 }}>
      ✓ Payment of ${appointment.copay} confirmed — a receipt has been sent to your email.
    </div>
  )

  return (
    <div style={{ marginTop: 16, borderTop: '0.5px solid #e2ddd6', paddingTop: 16 }}>
      <div style={{ fontSize: 12, color: '#8a8880', marginBottom: 8 }}>Pay copay — ${appointment.copay}</div>
      <div style={{
        border: '1px solid #e2ddd6', borderRadius: 8, padding: '10px 14px',
        background: '#fafaf8', marginBottom: 10,
      }}>
        <CardElement options={{ style: { base: { fontSize: '14px', color: '#1a1916' } } }} />
      </div>
      {error && <div style={{ fontSize: 12, color: '#c04020', marginBottom: 8 }}>{error}</div>}
      <button
        onClick={handlePay}
        disabled={loading}
        style={{
          width: '100%', padding: '10px', borderRadius: 8,
          background: loading ? '#e2ddd6' : '#0d6b52',
          border: 'none', color: '#fff', fontSize: 14,
          cursor: loading ? 'not-allowed' : 'pointer', fontFamily: 'inherit',
        }}
      >
        {loading ? 'Processing...' : `Pay $${appointment.copay}`}
      </button>
      <div style={{ fontSize: 11, color: '#8a8880', textAlign: 'center', marginTop: 6 }}>
        Test card: 4242 4242 4242 4242 · any expiry · any CVC
      </div>
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

  useEffect(() => {
    fetch(`${API}/portal/reschedule-slots?department=${encodeURIComponent(apt.department)}`)
      .then(r => r.json())
      .then(d => setSlots((d.slots || []).slice(0, 5)))
      .catch(() => setError('Could not load available times.'))
      .finally(() => setLoading(false))
  }, [apt.department])

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
        Choose a new time for {apt.department}:
      </div>
      {loading && <div style={{ fontSize: 13, color: '#8a8880' }}>Loading available times...</div>}
      {error && <div style={{ fontSize: 12, color: '#c04020', marginBottom: 8 }}>{error}</div>}
      {!loading && slots.length === 0 && !error && (
        <div style={{ fontSize: 13, color: '#8a8880' }}>No available slots found right now.</div>
      )}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {slots.map((s, i) => (
          <button
            key={i}
            onClick={() => confirmReschedule(s)}
            disabled={!!confirming}
            style={{
              textAlign: 'left', padding: '9px 14px', borderRadius: 8,
              border: '1px solid #e2ddd6',
              background: confirming === s ? '#e0f0ea' : '#fafaf8',
              color: '#1a1916', fontSize: 13, cursor: confirming ? 'not-allowed' : 'pointer',
              fontFamily: 'inherit',
            }}
          >
            {s.doctor} — {s.date} at {s.time}
          </button>
        ))}
      </div>
      <button
        onClick={onCancel}
        style={{
          marginTop: 10, fontSize: 12, color: '#8a8880', background: 'none',
          border: 'none', cursor: 'pointer', fontFamily: 'inherit',
        }}
      >
        Never mind
      </button>
    </div>
  )
}

function AppointmentCard({ apt, stripePromise, onPaid, onChanged }: {
  apt: Appointment
  stripePromise: any
  onPaid: () => void
  onChanged: () => void
}) {
  const [showPay, setShowPay] = useState(false)
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
        const body = await res.text()
        console.error('[portal] Cancel failed:', res.status, body)
        setCancelError(`Could not cancel (server said: ${res.status}). Check the backend terminal for details.`)
        return
      }
      onChanged()
    } catch (e) {
      console.error('[portal] Cancel request failed:', e)
      setCancelError('Could not reach the server — is the backend running?')
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
              <span style={{ fontSize: 11, color: '#c04020', marginLeft: 8, fontWeight: 500 }}>
                Cancelled
              </span>
            )}
          </div>
          <div style={{ fontSize: 13, color: '#8a8880' }}>
            {apt.appointment_date} · {apt.appointment_time} · {apt.department}
          </div>
          {apt.reason && (
            <div style={{ fontSize: 12, color: '#aaa', marginTop: 4 }}>
              Reason: {apt.reason}
            </div>
          )}
        </div>
        <div style={{ textAlign: 'right', flexShrink: 0, marginLeft: 16 }}>
          <div style={{
            fontSize: 11, padding: '3px 10px', borderRadius: 20,
            background: paid ? '#e0f0ea' : '#fdf0dc',
            color: paid ? '#0d6b52' : '#b06a10',
            marginBottom: 4,
          }}>
            {paid ? 'Paid ✓' : 'Unpaid'}
          </div>
          {paid && apt.payment_date && (
            <div style={{ fontSize: 11, color: '#8a8880', marginBottom: 4 }}>
              {apt.payment_date}
            </div>
          )}
          {apt.copay && apt.copay !== '0' && (
            <div style={{ fontSize: 13, color: '#4a4845' }}>
              Copay: ${apt.copay}
            </div>
          )}
          <div style={{ fontSize: 11, color: '#ccc', marginTop: 2 }}>
            {apt.payer}
          </div>
        </div>
      </div>

      {!cancelled && !paid && apt.copay && parseFloat(apt.copay) > 0 && (
        <>
          {!showPay ? (
            <button
              onClick={() => setShowPay(true)}
              style={{
                marginTop: 14, marginRight: 8, padding: '8px 18px', borderRadius: 8,
                background: 'transparent', border: '0.5px solid #0d6b52',
                color: '#0d6b52', fontSize: 13, cursor: 'pointer', fontFamily: 'inherit',
              }}
            >
              Pay now
            </button>
          ) : (
            <Elements stripe={stripePromise}>
              <PaymentForm appointment={apt} onPaid={onPaid} />
            </Elements>
          )}
        </>
      )}

      {!cancelled && !showReschedule && (
        <div style={{ marginTop: 14 }}>
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              onClick={() => setShowReschedule(true)}
              style={{
                padding: '8px 18px', borderRadius: 8,
                background: 'transparent', border: '0.5px solid #8a8880',
                color: '#4a4845', fontSize: 13, cursor: 'pointer', fontFamily: 'inherit',
              }}
            >
              Reschedule
            </button>
            <button
              onClick={handleCancel}
              disabled={cancelling}
              style={{
                padding: '8px 18px', borderRadius: 8,
                background: 'transparent', border: '0.5px solid #c04020',
                color: '#c04020', fontSize: 13,
                cursor: cancelling ? 'not-allowed' : 'pointer', fontFamily: 'inherit',
              }}
            >
              {cancelling ? 'Cancelling...' : 'Cancel appointment'}
            </button>
          </div>
          {cancelError && (
            <div style={{ fontSize: 12, color: '#c04020', marginTop: 8 }}>
              {cancelError}
            </div>
          )}
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

export default function PortalPage() {
  const [name, setName] = useState('')
  const [dob, setDob] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [appointments, setAppointments] = useState<Appointment[]>([])
  const [loggedIn, setLoggedIn] = useState(false)
  const [stripePromise, setStripePromise] = useState<any>(null)

  useEffect(() => {
    fetch(`${API}/payment/publishable-key`)
      .then(r => r.json())
      .then(d => setStripePromise(loadStripe(d.publishable_key)))
      .catch(() => {})
  }, [])

  const handleLookup = async () => {
    if (!name || !dob) return
    setLoading(true)
    setError('')
    try {
      const res = await fetch(`${API}/portal/lookup`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, dob }),
      })
      if (!res.ok) {
        setError('No records found. Check your name and date of birth.')
        return
      }
      const data = await res.json()
      setAppointments(data.patients)
      setLoggedIn(true)
    } catch {
      setError('Could not connect to server.')
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
            <a href="/" style={{
              color: 'rgba(255,255,255,0.4)', fontSize: 13, textDecoration: 'none',
              transition: 'color 0.15s',
            }}
              onMouseEnter={e => (e.currentTarget.style.color = '#fff')}
              onMouseLeave={e => (e.currentTarget.style.color = 'rgba(255,255,255,0.4)')}
            >
              ← Lea Medical Center
            </a>
            <div style={{ color: 'rgba(255,255,255,0.15)', fontSize: 13 }}>|</div>
            <div style={{ fontFamily: "'Fraunces', serif", fontSize: 18, color: '#fff', fontWeight: 300 }}>
              Patient <em style={{ color: '#9fb8ac', fontStyle: 'italic' }}>Portal</em>
            </div>
          </div>
          <div style={{ fontSize: 11, color: '#8a8880' }}>Ledelsea · Secure · HIPAA compliant</div>
        </div>

        <div style={{ maxWidth: 600, margin: '0 auto', padding: '40px 24px' }}>

          {!loggedIn ? (
            <div style={{
              background: '#fff', borderRadius: 16, border: '0.5px solid #e2ddd6',
              padding: '36px 32px',
            }}>
              <div style={{ fontSize: 22, fontWeight: 600, color: '#1a1916', marginBottom: 6 }}>
                View your statements
              </div>
              <div style={{ fontSize: 14, color: '#8a8880', marginBottom: 28 }}>
                Enter your name and date of birth to access your appointment history, pay any outstanding balances, or cancel/reschedule.
              </div>

              <div style={{ marginBottom: 16 }}>
                <label style={{ fontSize: 12, color: '#4a4845', display: 'block', marginBottom: 6 }}>Full name</label>
                <input
                  value={name}
                  onChange={e => setName(e.target.value)}
                  placeholder="e.g. Brandon Collins"
                  style={{
                    width: '100%', padding: '11px 14px', borderRadius: 8,
                    border: '1px solid #e2ddd6', fontSize: 14,
                    fontFamily: 'inherit', outline: 'none', boxSizing: 'border-box',
                  }}
                />
              </div>

              <div style={{ marginBottom: 24 }}>
                <label style={{ fontSize: 12, color: '#4a4845', display: 'block', marginBottom: 6 }}>Date of birth</label>
                <input
                  value={dob}
                  onChange={e => setDob(e.target.value)}
                  placeholder="MM/DD/YYYY"
                  style={{
                    width: '100%', padding: '11px 14px', borderRadius: 8,
                    border: '1px solid #e2ddd6', fontSize: 14,
                    fontFamily: 'inherit', outline: 'none', boxSizing: 'border-box',
                  }}
                />
              </div>

              {error && (
                <div style={{ fontSize: 13, color: '#c04020', marginBottom: 14 }}>{error}</div>
              )}

              <button
                onClick={handleLookup}
                disabled={loading || !name || !dob}
                style={{
                  width: '100%', padding: '12px', borderRadius: 8,
                  background: loading || !name || !dob ? '#e2ddd6' : '#0d6b52',
                  border: 'none', color: '#fff', fontSize: 14, fontWeight: 500,
                  cursor: loading || !name || !dob ? 'not-allowed' : 'pointer',
                  fontFamily: 'inherit',
                }}
              >
                {loading ? 'Looking up...' : 'View my records'}
              </button>
            </div>
          ) : (
            <>
              <div style={{ marginBottom: 24 }}>
                <div style={{ fontSize: 22, fontWeight: 600, color: '#1a1916' }}>
                  {appointments[0]?.name}
                </div>
                <div style={{ fontSize: 13, color: '#8a8880', marginTop: 4 }}>
                  DOB: {dob} · {appointments.length} appointment{appointments.length !== 1 ? 's' : ''}
                </div>
              </div>

              {totalUnpaid > 0 && (
                <div style={{
                  background: '#fdf0dc', border: '0.5px solid #f0c878',
                  borderRadius: 12, padding: '14px 20px', marginBottom: 20,
                  display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                }}>
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 500, color: '#b06a10' }}>Outstanding balance</div>
                    <div style={{ fontSize: 12, color: '#c8901a', marginTop: 2 }}>
                      {appointments.filter(a => a.appointment_status !== 'cancelled' && a.payment_status !== 'paid' && parseFloat(a.copay || '0') > 0).length} unpaid copay{appointments.filter(a => a.appointment_status !== 'cancelled' && a.payment_status !== 'paid' && parseFloat(a.copay || '0') > 0).length !== 1 ? 's' : ''}
                    </div>
                  </div>
                  <div style={{ fontSize: 22, fontWeight: 600, color: '#b06a10' }}>
                    ${totalUnpaid.toFixed(2)}
                  </div>
                </div>
              )}

              {totalUnpaid === 0 && (
                <div style={{
                  background: '#e0f0ea', border: '0.5px solid #9fd8c0',
                  borderRadius: 12, padding: '14px 20px', marginBottom: 20,
                  fontSize: 13, color: '#0d6b52',
                }}>
                  ✓ All balances paid — you're up to date
                </div>
              )}

              {appointments.map(apt => (
                <AppointmentCard
                  key={apt.patient_id}
                  apt={apt}
                  stripePromise={stripePromise}
                  onPaid={refresh}
                  onChanged={refresh}
                />
              ))}

              <button
                onClick={() => { setLoggedIn(false); setAppointments([]); setName(''); setDob('') }}
                style={{
                  marginTop: 8, fontSize: 13, color: '#8a8880', background: 'none',
                  border: 'none', cursor: 'pointer', fontFamily: 'inherit',
                }}
              >
                ← Sign out
              </button>
            </>
          )}
        </div>
      </div>
    </>
  )
}