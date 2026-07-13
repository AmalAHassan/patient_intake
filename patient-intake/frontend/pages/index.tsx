import { useState } from 'react'
import Head from 'next/head'
import { useRouter } from 'next/router'

export default function HomePage() {
  const [chatOpen, setChatOpen] = useState(false)
  const router = useRouter()

  return (
    <>
      <Head>
        <title>Ledelsea Health — AI Patient Intake</title>
        <link href="https://fonts.googleapis.com/css2?family=Barlow:wght@300;400;500;600;700&family=Barlow+Condensed:wght@500;600;700&display=swap" rel="stylesheet" />
      </Head>

      <style>{`
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: 'Barlow', sans-serif; background: #faf8f5; color: #1a1008; overflow-x: hidden; }

        nav {
          position: sticky; top: 0; z-index: 100;
          background: rgba(250,248,245,0.95);
          backdrop-filter: blur(8px);
          border-bottom: 1px solid #e8ddd6;
          padding: 0 48px;
          display: flex; align-items: center; justify-content: space-between;
          height: 64px;
        }
        .nav-logo {
          display: flex; align-items: center; gap: 10px;
          font-family: 'Barlow Condensed', sans-serif;
          font-size: 20px; font-weight: 700;
          letter-spacing: 0.06em; text-transform: uppercase;
          color: #2c1a14; text-decoration: none;
        }
        .nav-links { display: flex; align-items: center; gap: 32px; }
        .nav-links a {
          font-size: 14px; color: #5a4a44; text-decoration: none;
          font-weight: 500; letter-spacing: 0.01em; transition: color 0.15s;
        }
        .nav-links a:hover { color: #8b5e52; }
        .nav-cta {
          background: #2c1a14 !important; color: #fff !important;
          padding: 8px 20px; border-radius: 8px;
          font-size: 13px !important; font-weight: 600 !important;
        }
        .nav-cta:hover { background: #8b5e52 !important; }

        .hero {
          max-width: 1100px; margin: 0 auto;
          padding: 80px 48px 60px;
          display: grid; grid-template-columns: 1fr 1fr;
          gap: 64px; align-items: center;
        }
        .eyebrow {
          font-size: 11px; font-weight: 600; letter-spacing: 0.12em;
          text-transform: uppercase; color: #8b5e52; margin-bottom: 16px;
        }
        h1 {
          font-family: 'Barlow Condensed', sans-serif;
          font-size: 52px; font-weight: 700; line-height: 1.05;
          color: #2c1a14; margin-bottom: 20px; letter-spacing: -0.01em;
        }
        h1 span { color: #8b5e52; }
        .hero-sub {
          font-size: 16px; color: #6b5a52; line-height: 1.65;
          margin-bottom: 32px; max-width: 420px;
        }
        .hero-actions { display: flex; gap: 12px; align-items: center; }
        .btn-primary {
          background: #8b5e52; color: #fff;
          padding: 12px 24px; border-radius: 10px; border: none;
          font-family: 'Barlow', sans-serif; font-size: 14px; font-weight: 600;
          cursor: pointer; letter-spacing: 0.02em; transition: background 0.15s;
        }
        .btn-primary:hover { background: #6b3d30; }
        .btn-secondary {
          background: transparent; color: #2c1a14;
          padding: 12px 24px; border-radius: 10px;
          border: 1.5px solid #d4c4bc;
          font-family: 'Barlow', sans-serif; font-size: 14px; font-weight: 500;
          cursor: pointer; transition: all 0.15s;
        }
        .btn-secondary:hover { border-color: #8b5e52; color: #8b5e52; }

        .hero-card {
          background: #fff; border-radius: 20px;
          border: 1px solid #e8ddd6; padding: 28px;
          box-shadow: 0 4px 24px rgba(44,26,20,0.08);
        }
        .hero-card-header {
          display: flex; align-items: center; gap: 12px; margin-bottom: 20px;
        }
        .avatar {
          width: 44px; height: 44px; border-radius: 50%;
          background: #f5ede6; display: flex; align-items: center;
          justify-content: center; font-size: 20px; flex-shrink: 0;
        }
        .status-dot {
          width: 8px; height: 8px; border-radius: 50%; background: #4caf7d;
          box-shadow: 0 0 0 3px rgba(76,175,125,0.2);
        }
        .steps { display: flex; flex-direction: column; gap: 10px; }
        .step {
          display: flex; align-items: center; gap: 12px;
          padding: 10px 14px; border-radius: 10px;
          background: #faf7f3; border: 1px solid #f0e8e0;
        }
        .step-icon {
          width: 28px; height: 28px; border-radius: 8px;
          display: flex; align-items: center; justify-content: center;
          font-size: 12px; flex-shrink: 0;
        }
        .step-badge {
          font-size: 10px; padding: 2px 8px; border-radius: 20px;
          font-weight: 600; letter-spacing: 0.04em;
        }

        .stats {
          background: #2c1a14; padding: 40px 48px;
          display: grid; grid-template-columns: repeat(4, 1fr);
        }
        .stat { padding: 0 32px; text-align: center; border-right: 1px solid rgba(255,255,255,0.08); }
        .stat:first-child { padding-left: 0; }
        .stat:last-child { border-right: none; padding-right: 0; }
        .stat-num {
          font-family: 'Barlow Condensed', sans-serif;
          font-size: 36px; font-weight: 700; color: #f5ede6;
          margin-bottom: 4px;
        }
        .stat-label { font-size: 11px; color: rgba(255,255,255,0.4); letter-spacing: 0.06em; text-transform: uppercase; }

        .services { padding: 80px 48px; max-width: 1100px; margin: 0 auto; }
        .section-title {
          font-family: 'Barlow Condensed', sans-serif;
          font-size: 36px; font-weight: 700; color: #2c1a14;
          margin-bottom: 48px; letter-spacing: -0.01em;
        }
        .services-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; }
        .service-card {
          background: #fff; border-radius: 16px;
          border: 1px solid #e8ddd6; padding: 28px;
          transition: box-shadow 0.2s, transform 0.2s;
        }
        .service-card:hover { box-shadow: 0 8px 24px rgba(44,26,20,0.1); transform: translateY(-2px); }
        .service-icon {
          width: 48px; height: 48px; border-radius: 12px;
          background: #f5ede6; display: flex; align-items: center;
          justify-content: center; font-size: 22px; margin-bottom: 16px;
        }
        .service-name { font-size: 16px; font-weight: 600; color: #2c1a14; margin-bottom: 8px; }
        .service-desc { font-size: 13px; color: #9e8880; line-height: 1.6; }

        .cta-band {
          background: #f5ede6; margin: 0 48px 80px;
          border-radius: 20px; padding: 48px;
          display: flex; align-items: center; justify-content: space-between; gap: 32px;
        }
        .cta-band-title {
          font-family: 'Barlow Condensed', sans-serif;
          font-size: 28px; font-weight: 700; color: #2c1a14; margin-bottom: 8px;
        }
        .cta-band-sub { font-size: 14px; color: #6b5a52; }

        footer {
          border-top: 1px solid #e8ddd6; padding: 32px 48px;
          display: flex; align-items: center; justify-content: space-between;
        }
        .footer-logo {
          font-family: 'Barlow Condensed', sans-serif;
          font-size: 16px; font-weight: 700; letter-spacing: 0.06em;
          text-transform: uppercase; color: #2c1a14;
        }

        /* Chat modal */
        .chat-overlay {
          position: fixed; inset: 0; z-index: 200;
          background: rgba(44,26,20,0.4);
          display: flex; align-items: center; justify-content: center;
          padding: 20px;
        }
        .chat-modal {
          background: #fff; border-radius: 20px; overflow: hidden;
          width: 100%; max-width: 480px; height: 700px;
          display: flex; flex-direction: column;
          box-shadow: 0 24px 64px rgba(44,26,20,0.25);
        }
        .chat-modal-header {
          background: #2c1a14; padding: 16px 20px;
          display: flex; align-items: center; justify-content: space-between;
          flex-shrink: 0;
        }
        .chat-modal-title {
          font-family: 'Barlow Condensed', sans-serif;
          font-size: 16px; font-weight: 700; color: #fff;
          letter-spacing: 0.04em; text-transform: uppercase;
          display: flex; align-items: center; gap: 8px;
        }
        .online-dot { width: 7px; height: 7px; border-radius: 50%; background: #4caf7d; }
        .chat-close-btn {
          background: none; border: none; color: rgba(255,255,255,0.5);
          cursor: pointer; font-size: 20px; line-height: 1; padding: 2px;
          transition: color 0.15s;
        }
        .chat-close-btn:hover { color: #fff; }

        /* Chat launcher */
        .launcher {
          position: fixed; bottom: 28px; right: 28px; z-index: 100;
          width: 56px; height: 56px; border-radius: 50%;
          background: #8b5e52; border: none; cursor: pointer;
          display: flex; align-items: center; justify-content: center;
          box-shadow: 0 4px 16px rgba(139,94,82,0.4);
          transition: background 0.15s, transform 0.2s;
        }
        .launcher:hover { background: #6b3d30; transform: scale(1.05); }
        .notif-dot {
          position: absolute; top: -2px; right: -2px;
          width: 16px; height: 16px; border-radius: 50%;
          background: #e53e3e; border: 2px solid #faf8f5;
          font-size: 9px; color: #fff; font-weight: 700;
          display: flex; align-items: center; justify-content: center;
        }

        @media (max-width: 768px) {
          .hero { grid-template-columns: 1fr; padding: 40px 24px; gap: 32px; }
          .services-grid { grid-template-columns: 1fr; }
          .stats { grid-template-columns: repeat(2, 1fr); gap: 20px; padding: 32px 24px; }
          .stat { border-right: none; padding: 0; }
          .cta-band { flex-direction: column; margin: 0 24px 48px; }
          nav { padding: 0 24px; }
          .nav-links a:not(.nav-cta) { display: none; }
          .services { padding: 48px 24px; }
          footer { padding: 24px; flex-direction: column; gap: 8px; text-align: center; }
        }
      `}</style>

      {/* Nav */}
      <nav>
        <a href="/" className="nav-logo">
          <svg width="22" height="26" viewBox="0 0 28 32" fill="none">
            <path d="M14 2L14 18M14 18L6 26M14 18L22 26M14 26L14 30M10 30L18 30" stroke="#8b5e52" strokeWidth="2" strokeLinecap="round"/>
            <circle cx="14" cy="6" r="3" fill="#8b5e52"/>
          </svg>
          Ledelsea Health
        </a>
        <div className="nav-links">
          <a href="#">Services</a>
          <a href="#">Providers</a>
          <a href="#">Locations</a>
          <a href="/portal">Patient portal</a>
          <a href="#" className="nav-cta" onClick={e => { e.preventDefault(); setChatOpen(true) }}>
            Book appointment
          </a>
        </div>
      </nav>

      {/* Hero */}
      <section className="hero">
        <div>
          <div className="eyebrow">AI-powered patient intake</div>
          <h1>Healthcare that <span>fits your life</span></h1>
          <p className="hero-sub">
            From first appointment to follow-up care, Ledelsea Health makes every step simple —
            with AI-assisted intake, real-time insurance verification, and seamless scheduling.
          </p>
          <div className="hero-actions">
            <button className="btn-primary" onClick={() => setChatOpen(true)}>Start intake now</button>
            <button className="btn-secondary" onClick={() => router.push('/portal')}>View portal</button>
          </div>
        </div>

        <div className="hero-card">
          <div className="hero-card-header">
            <div className="avatar">👤</div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 15, fontWeight: 600, color: '#2c1a14' }}>Patient Intake</div>
              <div style={{ fontSize: 12, color: '#9e8880', marginTop: 2 }}>Powered by Ledelsea AI</div>
            </div>
            <div className="status-dot" />
          </div>
          <div className="steps">
            {[
              { label: 'Identity verified', badge: 'Done', badgeBg: 'rgba(139,94,82,0.12)', badgeColor: '#8b5e52', iconBg: '#f5ede6', icon: '✓' },
              { label: 'Insurance confirmed', badge: 'Done', badgeBg: 'rgba(139,94,82,0.12)', badgeColor: '#8b5e52', iconBg: '#f5ede6', icon: '✓' },
              { label: 'Scheduling appointment', badge: 'Active', badgeBg: '#8b5e52', badgeColor: '#fff', iconBg: '#8b5e52', icon: '⋯', stepBg: '#f5ede6', stepBorder: '#d4c4bc' },
              { label: 'Consent and payment', badge: 'Pending', badgeBg: 'transparent', badgeColor: '#c4b4ac', iconBg: '#f0e8e0', icon: '○', opacity: 0.5 },
            ].map((s, i) => (
              <div key={i} className="step" style={{ background: s.stepBg, borderColor: s.stepBorder, opacity: s.opacity }}>
                <div className="step-icon" style={{ background: s.iconBg, color: s.iconBg === '#8b5e52' ? '#fff' : '#8b5e52', fontSize: 13 }}>{s.icon}</div>
                <span style={{ fontSize: 13, fontWeight: 500, color: '#2c1a14', flex: 1 }}>{s.label}</span>
                <span className="step-badge" style={{ background: s.badgeBg, color: s.badgeColor }}>{s.badge}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Stats */}
      <div className="stats">
        {[
          { num: '55,000+', label: 'Patients served' },
          { num: '< 90s',   label: 'Avg intake time' },
          { num: '12',      label: 'Departments' },
          { num: 'HIPAA',   label: 'Compliant' },
        ].map((s, i) => (
          <div key={i} className="stat">
            <div className="stat-num">{s.num}</div>
            <div className="stat-label">{s.label}</div>
          </div>
        ))}
      </div>

      {/* Services */}
      <section className="services">
        <div className="eyebrow">What we offer</div>
        <h2 className="section-title">Comprehensive care, simplified</h2>
        <div className="services-grid">
          {[
            { icon: '🏥', name: 'Family Medicine',  desc: 'Primary care for every stage of life. Annual checkups, chronic disease management, and preventive care.' },
            { icon: '❤️', name: 'Cardiology',       desc: 'Heart health monitoring, echocardiograms, and preventive cardiovascular care by board-certified specialists.' },
            { icon: '🧠', name: 'Mental Health',    desc: 'Therapy, psychiatry, and crisis support. Confidential, compassionate care for your wellbeing.' },
            { icon: '🚑', name: 'Urgent Care',      desc: 'Walk-in care for non-life-threatening conditions. Fast treatment, no appointment needed.' },
            { icon: '👶', name: 'Pediatrics',       desc: 'Specialized care for infants, children, and adolescents. Vaccinations, growth tracking, and more.' },
            { icon: '🔬', name: 'Dermatology',      desc: 'Skin health, acne treatment, mole checks, and cosmetic procedures by certified dermatologists.' },
          ].map((s, i) => (
            <div key={i} className="service-card" onClick={() => setChatOpen(true)} style={{ cursor: 'pointer' }}>
              <div className="service-icon">{s.icon}</div>
              <div className="service-name">{s.name}</div>
              <div className="service-desc">{s.desc}</div>
            </div>
          ))}
        </div>
      </section>

      {/* CTA band */}
      <div className="cta-band">
        <div>
          <div className="cta-band-title">Ready to book your appointment?</div>
          <div className="cta-band-sub">Our AI intake takes under 90 seconds. Insurance verified instantly.</div>
        </div>
        <button className="btn-primary" style={{ padding: '14px 28px', flexShrink: 0 }} onClick={() => setChatOpen(true)}>
          Start intake →
        </button>
      </div>

      {/* Footer */}
      <footer>
        <div className="footer-logo">Ledelsea Health</div>
        <div style={{ fontSize: 12, color: '#c4b4ac' }}>HIPAA compliant · NIST IAL2 · © 2026 Ledelsea</div>
      </footer>

      {/* Chat launcher */}
      <button className="launcher" onClick={() => setChatOpen(true)} style={{ position: 'fixed' }}>
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
        </svg>
        <div className="notif-dot">1</div>
      </button>

      {/* Chat modal */}
      {chatOpen && (
        <div className="chat-overlay" onClick={e => { if (e.target === e.currentTarget) setChatOpen(false) }}>
          <div className="chat-modal">
            <div className="chat-modal-header">
              <div className="chat-modal-title">
                <div className="online-dot" />
                Patient Intake
              </div>
              <button className="chat-close-btn" onClick={() => setChatOpen(false)}>✕</button>
            </div>
            <iframe
              src="/intake"
              style={{ flex: 1, border: 'none', width: '100%' }}
              title="Patient Intake"
            />
          </div>
        </div>
      )}
    </>
  )
}