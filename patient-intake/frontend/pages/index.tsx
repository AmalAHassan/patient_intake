import { useState } from 'react'
import Head from 'next/head'
import { useRouter } from 'next/router'

export default function HomePage() {
  const [chatOpen, setChatOpen] = useState(false)
  const router = useRouter()

  return (
    <>
      <Head>
        <title>Lea Medical Center</title>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Playfair+Display:wght@600;700&display=swap" rel="stylesheet" />
      </Head>

      <style>{`
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: 'Inter', sans-serif; background: #fff; color: #0a1628; overflow-x: hidden; }

        nav {
          position: sticky; top: 0; z-index: 100;
          background: rgba(255,255,255,0.97);
          backdrop-filter: blur(8px);
          border-bottom: 1px solid #e8edf5;
          padding: 0 56px;
          display: flex; align-items: center; justify-content: space-between;
          height: 68px;
        }
        .nav-logo {
          display: flex; align-items: center; gap: 10px;
          font-size: 18px; font-weight: 700; color: #0a1628;
          text-decoration: none; letter-spacing: -0.01em;
        }
        .nav-logo-icon {
          width: 32px; height: 32px; border-radius: 8px;
          background: #1a5ce4; display: flex; align-items: center;
          justify-content: center;
        }
        .nav-links { display: flex; align-items: center; gap: 28px; }
        .nav-links a {
          font-size: 14px; color: #4a5568; text-decoration: none;
          font-weight: 500; transition: color 0.15s;
        }
        .nav-links a:hover { color: #1a5ce4; }
        .nav-cta {
          background: #1a5ce4 !important; color: #fff !important;
          padding: 9px 20px; border-radius: 8px;
          font-size: 13px !important; font-weight: 600 !important;
          transition: background 0.15s !important;
        }
        .nav-cta:hover { background: #1449c0 !important; }

        .hero {
          background: linear-gradient(135deg, #f0f5ff 0%, #ffffff 60%);
          padding: 80px 56px;
          display: grid; grid-template-columns: 1fr 1fr;
          gap: 64px; align-items: center;
          max-width: 1200px; margin: 0 auto;
        }
        .hero-tag {
          display: inline-flex; align-items: center; gap: 6px;
          background: #e8f0fe; color: #1a5ce4;
          font-size: 12px; font-weight: 600; letter-spacing: 0.04em;
          padding: 5px 12px; border-radius: 20px; margin-bottom: 20px;
        }
        .hero-tag-dot { width: 6px; height: 6px; border-radius: 50%; background: #1a5ce4; }
        h1 {
          font-family: 'Playfair Display', serif;
          font-size: 48px; font-weight: 700; line-height: 1.1;
          color: #0a1628; margin-bottom: 20px; letter-spacing: -0.02em;
        }
        h1 em { color: #1a5ce4; font-style: normal; }
        .hero-sub {
          font-size: 16px; color: #4a5568; line-height: 1.7;
          margin-bottom: 36px; max-width: 440px;
        }
        .hero-actions { display: flex; gap: 12px; flex-wrap: wrap; }
        .btn-blue {
          background: #1a5ce4; color: #fff;
          padding: 13px 26px; border-radius: 10px; border: none;
          font-family: 'Inter', sans-serif; font-size: 14px; font-weight: 600;
          cursor: pointer; transition: background 0.15s;
        }
        .btn-blue:hover { background: #1449c0; }
        .btn-outline {
          background: transparent; color: #0a1628;
          padding: 13px 26px; border-radius: 10px;
          border: 1.5px solid #d1dae8;
          font-family: 'Inter', sans-serif; font-size: 14px; font-weight: 500;
          cursor: pointer; transition: all 0.15s;
        }
        .btn-outline:hover { border-color: #1a5ce4; color: #1a5ce4; }

        .hero-visual {
          background: #fff; border-radius: 20px;
          border: 1px solid #e8edf5; padding: 28px;
          box-shadow: 0 8px 40px rgba(26,92,228,0.08);
        }
        .lea-header {
          display: flex; align-items: center; gap: 12px; margin-bottom: 20px;
          padding-bottom: 16px; border-bottom: 1px solid #f0f4fb;
        }
        .lea-avatar {
          width: 40px; height: 40px; border-radius: 10px;
          background: #1a5ce4; display: flex; align-items: center;
          justify-content: center; font-size: 18px; color: #fff; font-weight: 700;
          font-family: 'Playfair Display', serif;
        }
        .online-pill {
          display: flex; align-items: center; gap: 5px;
          background: #f0faf4; border: 1px solid #c6f0d4;
          border-radius: 20px; padding: 3px 10px;
          font-size: 11px; font-weight: 600; color: #1a7f3c;
        }
        .online-dot { width: 6px; height: 6px; border-radius: 50%; background: #22c55e; }

        .dept-list { display: flex; flex-direction: column; gap: 8px; }
        .dept-item {
          display: flex; align-items: center; gap: 12px;
          padding: 11px 14px; border-radius: 10px;
          border: 1px solid #f0f4fb; background: #fafbff;
          transition: all 0.15s; cursor: pointer;
        }
        .dept-item:hover { border-color: #1a5ce4; background: #f0f5ff; }
        .dept-dot {
          width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0;
        }
        .dept-name { font-size: 13px; font-weight: 500; color: #0a1628; flex: 1; }
        .dept-avail { font-size: 11px; color: #1a5ce4; font-weight: 500; }

        .stats-bar {
          background: #0a1628; padding: 36px 56px;
          display: grid; grid-template-columns: repeat(4,1fr);
        }
        .stat { text-align: center; padding: 0 24px; border-right: 1px solid rgba(255,255,255,0.08); }
        .stat:last-child { border-right: none; }
        .stat-num {
          font-family: 'Playfair Display', serif;
          font-size: 32px; font-weight: 700; color: #fff; margin-bottom: 4px;
        }
        .stat-label { font-size: 11px; color: rgba(255,255,255,0.4); letter-spacing: 0.06em; text-transform: uppercase; }

        .services-section { padding: 80px 56px; max-width: 1200px; margin: 0 auto; }
        .section-label {
          font-size: 12px; font-weight: 600; letter-spacing: 0.08em;
          text-transform: uppercase; color: #1a5ce4; margin-bottom: 12px;
        }
        h2 {
          font-family: 'Playfair Display', serif;
          font-size: 34px; font-weight: 700; color: #0a1628;
          margin-bottom: 48px; letter-spacing: -0.02em;
        }
        .dept-grid { display: grid; grid-template-columns: repeat(3,1fr); gap: 20px; }
        .dept-card {
          background: #fff; border-radius: 16px;
          border: 1px solid #e8edf5; padding: 28px;
          transition: all 0.2s; cursor: pointer;
        }
        .dept-card:hover {
          border-color: #1a5ce4; box-shadow: 0 8px 24px rgba(26,92,228,0.1);
          transform: translateY(-2px);
        }
        .dept-card-icon {
          width: 48px; height: 48px; border-radius: 12px;
          background: #f0f5ff; display: flex; align-items: center;
          justify-content: center; font-size: 22px; margin-bottom: 16px;
        }
        .dept-card-name { font-size: 15px; font-weight: 600; color: #0a1628; margin-bottom: 6px; }
        .dept-card-desc { font-size: 13px; color: #718096; line-height: 1.6; margin-bottom: 16px; }
        .dept-card-link {
          font-size: 13px; font-weight: 600; color: #1a5ce4;
          display: flex; align-items: center; gap: 4px;
        }

        .lea-band {
          background: #f0f5ff; margin: 0 56px 80px;
          border-radius: 20px; padding: 48px 56px;
          display: flex; align-items: center; justify-content: space-between; gap: 32px;
          border: 1px solid #d4e2fb;
        }
        .lea-band-tag {
          display: inline-flex; align-items: center; gap: 6px;
          background: #1a5ce4; color: #fff;
          font-size: 11px; font-weight: 700; letter-spacing: 0.06em;
          padding: 4px 10px; border-radius: 20px; margin-bottom: 12px;
          text-transform: uppercase;
        }
        .lea-band-title {
          font-family: 'Playfair Display', serif;
          font-size: 26px; font-weight: 700; color: #0a1628; margin-bottom: 8px;
        }
        .lea-band-sub { font-size: 14px; color: #4a5568; }

        footer {
          border-top: 1px solid #e8edf5; padding: 32px 56px;
          display: flex; align-items: center; justify-content: space-between;
        }
        .footer-logo { font-size: 15px; font-weight: 700; color: #0a1628; }
        .footer-links { display: flex; gap: 24px; }
        .footer-links a { font-size: 13px; color: #718096; text-decoration: none; }
        .footer-links a:hover { color: #1a5ce4; }

        .launcher {
          position: fixed; bottom: 28px; right: 28px; z-index: 100;
          display: flex; align-items: center; gap: 10px;
          background: #1a5ce4; border: none; cursor: pointer;
          padding: 14px 20px; border-radius: 50px;
          box-shadow: 0 4px 20px rgba(26,92,228,0.35);
          transition: all 0.2s; color: #fff;
          font-family: 'Inter', sans-serif;
        }
        .launcher:hover { background: #1449c0; transform: translateY(-2px); }
        .launcher-text { font-size: 14px; font-weight: 600; }
        .launcher-badge {
          width: 18px; height: 18px; border-radius: 50%;
          background: #ef4444; font-size: 10px; font-weight: 700;
          display: flex; align-items: center; justify-content: center;
        }

        .chat-overlay {
          position: fixed; inset: 0; z-index: 200;
          background: rgba(10,22,40,0.5);
          display: flex; align-items: center; justify-content: center; padding: 20px;
        }
        .chat-modal {
          background: #fff; border-radius: 20px; overflow: hidden;
          width: 100%; max-width: 480px; height: 700px;
          display: flex; flex-direction: column;
          box-shadow: 0 24px 64px rgba(10,22,40,0.25);
        }
        .chat-header {
          background: #0a1628; padding: 16px 20px;
          display: flex; align-items: center; justify-content: space-between; flex-shrink: 0;
        }
        .chat-header-left { display: flex; align-items: center; gap: 10px; }
        .chat-avatar {
          width: 32px; height: 32px; border-radius: 8px;
          background: #1a5ce4; display: flex; align-items: center;
          justify-content: center; font-size: 14px; font-weight: 700;
          color: #fff; font-family: 'Playfair Display', serif;
        }
        .chat-title { font-size: 15px; font-weight: 600; color: #fff; }
        .chat-subtitle { font-size: 11px; color: rgba(255,255,255,0.5); margin-top: 1px; }
        .chat-close {
          background: none; border: none; color: rgba(255,255,255,0.5);
          cursor: pointer; font-size: 20px; line-height: 1; padding: 2px;
          transition: color 0.15s;
        }
        .chat-close:hover { color: #fff; }

        @media (max-width: 768px) {
          .hero { grid-template-columns: 1fr; padding: 40px 24px; gap: 32px; }
          .dept-grid { grid-template-columns: 1fr; }
          .stats-bar { grid-template-columns: repeat(2,1fr); gap: 20px; padding: 32px 24px; }
          .stat { border-right: none; }
          nav { padding: 0 24px; }
          .nav-links a:not(.nav-cta) { display: none; }
          .services-section { padding: 48px 24px; }
          .lea-band { flex-direction: column; margin: 0 24px 48px; padding: 32px 28px; }
          footer { padding: 24px; flex-direction: column; gap: 16px; text-align: center; }
          .launcher-text { display: none; }
          .launcher { padding: 14px; border-radius: 50%; }
        }
      `}</style>

      {/* Nav */}
      <nav>
        <a href="/" className="nav-logo">
          <div className="nav-logo-icon">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round">
              <path d="M12 2L12 22M2 12L22 12" />
            </svg>
          </div>
          Lea Medical Center
        </a>
        <div className="nav-links">
          <a href="/departments">Departments</a>
          <a href="#">Providers</a>
          <a href="#">Locations</a>
          <a href="/portal">Patient portal</a>
          <a href="#" className="nav-cta" onClick={e => { e.preventDefault(); setChatOpen(true) }}>
            Book appointment
          </a>
        </div>
      </nav>

      {/* Hero */}
      <div style={{ background: 'linear-gradient(160deg, #f0f5ff 0%, #ffffff 55%)' }}>
        <section className="hero">
          <div>
            <div className="hero-tag">
              <div className="hero-tag-dot" />
              Lea Health AI — Now available
            </div>
            <h1>Advanced care,<br /><em>closer to you</em></h1>
            <p className="hero-sub">
              Lea Medical Center combines world-class specialists with AI-powered intake through Lea Health —
              so you spend less time on paperwork and more time getting better.
            </p>
            <div className="hero-actions">
              <button className="btn-blue" onClick={() => setChatOpen(true)}>Book with Lea Health</button>
              <button className="btn-outline" onClick={() => router.push('/departments')}>View departments</button>
            </div>
          </div>

          <div className="hero-visual">
            <div className="lea-header">
              <div className="lea-avatar">L</div>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 15, fontWeight: 600, color: '#0a1628' }}>Lea Health</div>
                <div style={{ fontSize: 12, color: '#718096', marginTop: 1 }}>AI patient intake by Lea Medical</div>
              </div>
              <div className="online-pill">
                <div className="online-dot" />
                Online
              </div>
            </div>
            <div className="dept-list">
              {[
                { name: 'Family Medicine', avail: '3 slots today', color: '#22c55e' },
                { name: 'Cardiology', avail: '1 slot today', color: '#f59e0b' },
                { name: 'Mental Health', avail: '5 slots today', color: '#22c55e' },
                { name: 'Pediatrics', avail: '2 slots today', color: '#22c55e' },
              ].map((d, i) => (
                <div key={i} className="dept-item" onClick={() => setChatOpen(true)}>
                  <div className="dept-dot" style={{ background: d.color }} />
                  <span className="dept-name">{d.name}</span>
                  <span className="dept-avail">{d.avail}</span>
                </div>
              ))}
              <button className="btn-blue" style={{ width: '100%', marginTop: 4, padding: '11px' }} onClick={() => setChatOpen(true)}>
                Start intake with Lea →
              </button>
            </div>
          </div>
        </section>
      </div>

      {/* Stats */}
      <div className="stats-bar">
        {[
          { num: '55,000+', label: 'Patients served' },
          { num: '< 90s',   label: 'Avg intake time' },
          { num: '12',      label: 'Departments' },
          { num: 'HIPAA',   label: 'Certified' },
        ].map((s, i) => (
          <div key={i} className="stat">
            <div className="stat-num">{s.num}</div>
            <div className="stat-label">{s.label}</div>
          </div>
        ))}
      </div>

      {/* Departments */}
      <section className="services-section">
        <div className="section-label">Our specialties</div>
        <h2>World-class care in every department</h2>
        <div className="dept-grid">
          {[
            { icon: '🏥', name: 'Family Medicine',  desc: 'Primary care for every stage of life — checkups, chronic disease management, and preventive care.' },
            { icon: '❤️', name: 'Cardiology',       desc: 'Heart health monitoring, echocardiograms, and preventive cardiovascular care by board-certified specialists.' },
            { icon: '🧠', name: 'Mental Health',    desc: 'Therapy, psychiatry, and crisis support. Confidential, compassionate care for your wellbeing.' },
            { icon: '🚑', name: 'Urgent Care',      desc: 'Walk-in care for non-life-threatening conditions. Fast treatment, no appointment needed.' },
            { icon: '👶', name: 'Pediatrics',       desc: 'Specialized care for children and adolescents — vaccinations, growth tracking, and more.' },
            { icon: '🔬', name: 'Dermatology',      desc: 'Skin health, acne treatment, mole checks, and cosmetic procedures by certified dermatologists.' },
          ].map((d, i) => (
            <div key={i} className="dept-card" onClick={() => setChatOpen(true)}>
              <div className="dept-card-icon">{d.icon}</div>
              <div className="dept-card-name">{d.name}</div>
              <div className="dept-card-desc">{d.desc}</div>
              <div className="dept-card-link">Book with Lea Health →</div>
            </div>
          ))}
        </div>
      </section>

      {/* Lea Health band */}
      <div className="lea-band">
        <div>
          <div className="lea-band-tag">Powered by Lea Health AI</div>
          <div className="lea-band-title">Book your appointment in under 90 seconds</div>
          <div className="lea-band-sub">Insurance verified instantly. No phone calls. No paperwork. Just care.</div>
        </div>
        <button className="btn-blue" style={{ padding: '14px 32px', flexShrink: 0, fontSize: 15 }} onClick={() => setChatOpen(true)}>
          Start now →
        </button>
      </div>

      {/* Footer */}
      <footer>
        <div className="footer-logo">Lea Medical Center</div>
        <div className="footer-links">
          <a href="/departments">Departments</a>
          <a href="/portal">Patient portal</a>
          <a href="#">Privacy</a>
          <a href="#">Contact</a>
        </div>
        <div style={{ fontSize: 12, color: '#a0aec0' }}>HIPAA compliant · © 2026 Lea Medical Center</div>
      </footer>

      {/* Launcher */}
      <button className="launcher" onClick={() => setChatOpen(true)}>
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
        </svg>
        <span className="launcher-text">Talk to Lea Health</span>
        <div className="launcher-badge">1</div>
      </button>

      {/* Chat modal */}
      {chatOpen && (
        <div className="chat-overlay" onClick={e => { if (e.target === e.currentTarget) setChatOpen(false) }}>
          <div className="chat-modal">
            <div className="chat-header">
              <div className="chat-header-left">
                <div className="chat-avatar">L</div>
                <div>
                  <div className="chat-title">Lea Health</div>
                  <div className="chat-subtitle">AI patient intake · Lea Medical Center</div>
                </div>
              </div>
              <button className="chat-close" onClick={() => setChatOpen(false)}>✕</button>
            </div>
            <iframe src="/intake" style={{ flex: 1, border: 'none', width: '100%' }} title="Lea Health Intake" />
          </div>
        </div>
      )}
    </>
  )
}