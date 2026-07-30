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

    // One quick check on load — the webhook usually beats this page's
    // load time, but if not, we still show something honest rather than
    // a false "paid" claim.
    fetch(`${API}/payment/status-by-session/${session_id}`)
      .then(r => r.json())
      .then(d => setStatus(d.paid ? 'paid' : 'pending'))
      .catch(() => setStatus('pending'))
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
                Payment received
              </div>
              <div style={{ fontSize: 14, color: '#6b4a40' }}>
                Thank you! You can close this tab and return to your registration.
              </div>
            </>
          )}
          {status === 'pending' && (
            <>
              <div style={{ fontSize: 18, fontWeight: 600, color: '#2c1a14', marginBottom: 8 }}>
                Payment submitted
              </div>
              <div style={{ fontSize: 14, color: '#6b4a40' }}>
                We're still confirming this with our payment provider — you're welcome
                to close this tab. If anything's wrong, you'll see it reflected in your
                patient portal shortly.
              </div>
            </>
          )}
        </div>
      </div>
    </>
  )
}