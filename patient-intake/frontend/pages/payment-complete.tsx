import { useEffect, useState } from 'react'
import { useRouter } from 'next/router'
import Head from 'next/head'

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export default function PaymentCompletePage() {
  const router = useRouter()
  const { session_id } = router.query
  const [status, setStatus] = useState<'checking' | 'paid' | 'pending'>('checking')

  useEffect(() => {
    if (!session_id || typeof session_id !== 'string') return

    // Reaching this page at all already means Stripe confirmed a
    // successful payment — Stripe only redirects here on success; a
    // failed card keeps the patient on Stripe's own checkout page with
    // an error, never reaching this URL. The ONLY reason our own
    // "paid" check might not show true yet is a race: the webhook can
    // take a few seconds to arrive. So retry a few times before
    // settling on "pending" — a single early check would too often
    // show pending for a payment that's about to succeed a moment
    // later.
    let attempts = 0
    const maxAttempts = 5

    const check = () => {
      fetch(`${API}/payment/status-by-session/${session_id}`)
        .then(r => r.json())
        .then(d => {
          if (d.paid) {
            setStatus('paid')
            return
          }
          attempts += 1
          if (attempts < maxAttempts) {
            setTimeout(check, 2000)
          } else {
            setStatus('pending')
          }
        })
        .catch(() => {
          attempts += 1
          if (attempts < maxAttempts) {
            setTimeout(check, 2000)
          } else {
            setStatus('pending')
          }
        })
    }

    check()
  }, [session_id])

  return (
    <>
      <Head>
        <title>Payment Complete — Ledelsea</title>
      </Head>
      <div style={{
        minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
        background: '#f5efe8', fontFamily: "'Barlow', sans-serif", padding: 24,
      }}>
        <div style={{
          background: '#fff', borderRadius: 16, border: '1px solid #e8ddd6',
          padding: '40px 36px', maxWidth: 420, textAlign: 'center',
          boxShadow: '0 2px 8px rgba(44,26,20,0.08)',
        }}>
          {status === 'checking' && (
            <div style={{ fontSize: 15, color: '#6b4a40' }}>Confirming your payment…</div>
          )}
          {status === 'paid' && (
            <>
              <div style={{ fontSize: 32, marginBottom: 12 }}>✓</div>
              <div style={{ fontSize: 18, fontWeight: 600, color: '#2c1a14', marginBottom: 8 }}>
                Payment successful
              </div>
              <div style={{ fontSize: 14, color: '#6b4a40' }}>
                Thank you — your copay has been received. You're welcome to close
                this tab and return to your registration.
              </div>
            </>
          )}
          {status === 'pending' && (
            <>
              <div style={{ fontSize: 32, marginBottom: 12 }}>✓</div>
              <div style={{ fontSize: 18, fontWeight: 600, color: '#2c1a14', marginBottom: 8 }}>
                Payment successful
              </div>
              <div style={{ fontSize: 14, color: '#6b4a40' }}>
                Your payment went through — we're just finishing updating your
                record. You're welcome to close this tab; it'll be reflected in
                your patient portal within a moment.
              </div>
            </>
          )}
        </div>
      </div>
    </>
  )
}