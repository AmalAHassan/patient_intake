import { useState } from 'react'
import Head from 'next/head'
import { useRouter } from 'next/router'

const PAGE_STYLES = `
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: 'Inter', sans-serif; background: #fff; color: #0a1628; overflow-x: hidden; }

        /* Nav */
        nav {
          background: #fff; border-bottom: 1px solid #e8edf5;
          padding: 0 56px; display: flex; align-items: center;
          justify-content: space-between; height: 70px;
          position: sticky; top: 0; z-index: 100;
          box-shadow: 0 1px 4px rgba(0,0,0,0.04);
        }
        .logo { display: flex; align-items: center; gap: 10px; text-decoration: none; }
        .logo-icon {
          width: 36px; height: 36px; border-radius: 8px; background: #1a5ce4;
          display: flex; align-items: center; justify-content: center;
        }
        .logo-text { font-size: 17px; font-weight: 700; color: #0a1628; letter-spacing: -0.01em; }
        .nav-center { display: flex; align-items: center; gap: 32px; }
        .nav-center a {
          font-size: 14px; color: #4a5568; text-decoration: none; font-weight: 500;
          cursor: default; opacity: 0.7;
        }
        .nav-right { display: flex; align-items: center; gap: 12px; }
        .nav-phone { font-size: 13px; font-weight: 600; color: #0a1628; }
        .btn-book {
          background: #1a5ce4; color: #fff; border: none; cursor: pointer;
          padding: 10px 22px; border-radius: 8px; font-size: 13px; font-weight: 600;
          font-family: 'Inter', sans-serif; transition: background 0.15s;
        }
        .btn-book:hover { background: #1449c0; }

        /* Top bar */
        .top-bar {
          background: #0a1628; padding: 8px 56px;
          display: flex; justify-content: space-between; align-items: center;
        }
        .top-bar-left { display: flex; gap: 24px; }
        .top-bar-left span { font-size: 12px; color: rgba(255,255,255,0.6); display: flex; align-items: center; gap: 6px; }
        .top-bar-right { font-size: 12px; color: rgba(255,255,255,0.6); }

        /* Hero */
        .hero {
          background: linear-gradient(135deg, #0a1628 0%, #1a3a6e 100%);
          padding: 80px 56px; display: grid;
          grid-template-columns: 1fr 1fr; gap: 64px; align-items: center;
        }
        .hero-label {
          display: inline-flex; align-items: center; gap: 6px;
          background: rgba(255,255,255,0.1); border: 1px solid rgba(255,255,255,0.15);
          color: #7eb3ff; font-size: 12px; font-weight: 600; letter-spacing: 0.04em;
          padding: 5px 12px; border-radius: 20px; margin-bottom: 20px;
        }
        .hero h1 {
          font-family: 'Playfair Display', serif;
          font-size: 46px; font-weight: 700; line-height: 1.1;
          color: #fff; margin-bottom: 18px; letter-spacing: -0.02em;
        }
        .hero h1 em { color: #7eb3ff; font-style: normal; }
        .hero-sub { font-size: 15px; color: rgba(255,255,255,0.65); line-height: 1.7; margin-bottom: 32px; max-width: 440px; }
        .hero-actions { display: flex; gap: 12px; flex-wrap: wrap; }
        .btn-white {
          background: #fff; color: #0a1628; border: none; cursor: pointer;
          padding: 13px 26px; border-radius: 10px; font-size: 14px; font-weight: 600;
          font-family: 'Inter', sans-serif; transition: opacity 0.15s;
        }
        .btn-white:hover { opacity: 0.9; }
        .btn-ghost {
          background: transparent; color: #fff; cursor: default;
          padding: 13px 26px; border-radius: 10px; font-size: 14px; font-weight: 500;
          font-family: 'Inter', sans-serif; border: 1.5px solid rgba(255,255,255,0.25);
          opacity: 0.7;
        }

        /* Hero image placeholder */
        .hero-image {
          background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1);
          border-radius: 20px; padding: 32px; display: flex; flex-direction: column; gap: 16px;
        }
        .doctor-card {
          background: rgba(255,255,255,0.08); border-radius: 12px; padding: 16px;
          display: flex; align-items: center; gap: 14px;
        }
        .doctor-avatar {
          width: 48px; height: 48px; border-radius: 50%; background: #1a5ce4;
          display: flex; align-items: center; justify-content: center;
          font-size: 18px; color: #fff; font-weight: 700; flex-shrink: 0;
        }
        .doctor-info { flex: 1; }
        .doctor-name { font-size: 14px; font-weight: 600; color: #fff; margin-bottom: 2px; }
        .doctor-role { font-size: 12px; color: rgba(255,255,255,0.5); }
        .avail-badge {
          background: rgba(34,197,94,0.2); border: 1px solid rgba(34,197,94,0.3);
          color: #4ade80; font-size: 11px; font-weight: 600;
          padding: 3px 10px; border-radius: 20px;
        }
        .hero-stats { display: grid; grid-template-columns: repeat(3,1fr); gap: 12px; }
        .hero-stat {
          background: rgba(255,255,255,0.06); border-radius: 10px; padding: 14px;
          text-align: center;
        }
        .hero-stat-num { font-size: 22px; font-weight: 700; color: #fff; font-family: 'Playfair Display', serif; }
        .hero-stat-label { font-size: 11px; color: rgba(255,255,255,0.4); margin-top: 2px; }

        /* Services strip */
        .services-strip {
          background: #f8faff; border-bottom: 1px solid #e8edf5;
          padding: 32px 56px; display: grid; grid-template-columns: repeat(6,1fr); gap: 0;
        }
        .service-item {
          text-align: center; padding: 20px 16px; cursor: default;
          border-right: 1px solid #e8edf5;
        }
        .service-item:last-child { border-right: none; }
        .service-item-icon { font-size: 28px; margin-bottom: 10px; }
        .service-item-name { font-size: 13px; font-weight: 600; color: #0a1628; margin-bottom: 4px; }
        .service-item-sub { font-size: 11px; color: #718096; }

        /* Why us */
        .why-section { padding: 80px 56px; max-width: 1200px; margin: 0 auto; }
        .section-eyebrow {
          font-size: 12px; font-weight: 600; letter-spacing: 0.08em;
          text-transform: uppercase; color: #1a5ce4; margin-bottom: 12px;
        }
        .section-h2 {
          font-family: 'Playfair Display', serif;
          font-size: 34px; font-weight: 700; color: #0a1628;
          margin-bottom: 48px; letter-spacing: -0.02em; max-width: 500px;
        }
        .why-grid { display: grid; grid-template-columns: repeat(3,1fr); gap: 24px; }
        .why-card {
          background: #fff; border-radius: 16px; border: 1px solid #e8edf5;
          padding: 28px; transition: box-shadow 0.2s;
        }
        .why-card:hover { box-shadow: 0 8px 24px rgba(26,92,228,0.08); }
        .why-icon {
          width: 48px; height: 48px; border-radius: 12px; background: #f0f5ff;
          display: flex; align-items: center; justify-content: center;
          font-size: 22px; margin-bottom: 16px;
        }
        .why-title { font-size: 15px; font-weight: 600; color: #0a1628; margin-bottom: 8px; }
        .why-desc { font-size: 13px; color: #718096; line-height: 1.65; }

        /* Doctors section */
        .doctors-section {
          background: #f8faff; padding: 80px 56px;
          border-top: 1px solid #e8edf5; border-bottom: 1px solid #e8edf5;
        }
        .doctors-inner { max-width: 1200px; margin: 0 auto; }
        .doctors-grid { display: grid; grid-template-columns: repeat(4,1fr); gap: 20px; margin-top: 48px; }
        .doc-card {
          background: #fff; border-radius: 16px; border: 1px solid #e8edf5;
          padding: 24px; text-align: center; cursor: default;
        }
        .doc-avatar {
          width: 72px; height: 72px; border-radius: 50%; margin: 0 auto 14px;
          display: flex; align-items: center; justify-content: center;
          font-size: 26px; font-weight: 700; color: #fff;
          font-family: 'Playfair Display', serif;
        }
        .doc-name { font-size: 15px; font-weight: 600; color: #0a1628; margin-bottom: 4px; }
        .doc-specialty { font-size: 13px; color: #1a5ce4; font-weight: 500; margin-bottom: 8px; }
        .doc-exp { font-size: 12px; color: #718096; }

        /* Lea's Health CTA */
        .lea-cta {
          background: linear-gradient(135deg, #1a5ce4 0%, #0a3a99 100%);
          padding: 80px 56px; text-align: center;
        }
        .lea-cta-tag {
          display: inline-flex; align-items: center; gap: 6px;
          background: rgba(255,255,255,0.15); color: #fff;
          font-size: 11px; font-weight: 700; letter-spacing: 0.08em;
          padding: 5px 14px; border-radius: 20px; margin-bottom: 20px;
          text-transform: uppercase;
        }
        .lea-cta h2 {
          font-family: 'Playfair Display', serif;
          font-size: 38px; font-weight: 700; color: #fff;
          margin-bottom: 16px; letter-spacing: -0.02em;
        }
        .lea-cta-sub { font-size: 16px; color: rgba(255,255,255,0.7); margin-bottom: 36px; }
        .lea-cta-actions { display: flex; gap: 12px; justify-content: center; flex-wrap: wrap; }

        /* Footer */
        .footer-main {
          background: #0a1628; padding: 56px 56px 32px;
        }
        .footer-grid { display: grid; grid-template-columns: 2fr 1fr 1fr 1fr; gap: 48px; margin-bottom: 48px; }
        .footer-brand { }
        .footer-logo-text { font-size: 18px; font-weight: 700; color: #fff; margin-bottom: 12px; display: flex; align-items: center; gap: 8px; }
        .footer-logo-icon { width: 28px; height: 28px; border-radius: 6px; background: #1a5ce4; display: flex; align-items: center; justify-content: center; }
        .footer-tagline { font-size: 13px; color: rgba(255,255,255,0.4); line-height: 1.7; max-width: 260px; }
        .footer-col h4 { font-size: 12px; font-weight: 600; color: rgba(255,255,255,0.3); letter-spacing: 0.08em; text-transform: uppercase; margin-bottom: 16px; }
        .footer-col a { display: block; font-size: 13px; color: rgba(255,255,255,0.5); text-decoration: none; margin-bottom: 10px; cursor: default; }
        .footer-bottom {
          border-top: 1px solid rgba(255,255,255,0.08); padding-top: 24px;
          display: flex; justify-content: space-between; align-items: center;
        }
        .footer-bottom-text { font-size: 12px; color: rgba(255,255,255,0.25); }

        /* Chat launcher */
        .launcher {
          position: fixed; bottom: 28px; right: 28px; z-index: 100;
          display: flex; align-items: center; gap: 10px;
          background: #1a5ce4; border: none; cursor: pointer;
          padding: 14px 20px; border-radius: 50px;
          box-shadow: 0 4px 20px rgba(26,92,228,0.4);
          transition: all 0.2s; color: #fff; font-family: 'Inter', sans-serif;
        }
        .launcher:hover { background: #1449c0; transform: translateY(-2px); }
        .launcher-text { font-size: 14px; font-weight: 600; }
        .launcher-badge {
          width: 18px; height: 18px; border-radius: 50%; background: #ef4444;
          font-size: 10px; font-weight: 700;
          display: flex; align-items: center; justify-content: center;
        }

        /* Chat modal */
        .chat-overlay {
          position: fixed; inset: 0; z-index: 200;
          background: rgba(10,22,40,0.6);
          display: flex; align-items: center; justify-content: center; padding: 20px;
        }
        .chat-modal {
          background: #fff; border-radius: 20px; overflow: hidden;
          width: 100%; max-width: 480px; height: 700px;
          display: flex; flex-direction: column;
          box-shadow: 0 24px 64px rgba(10,22,40,0.3);
        }
        .chat-header {
          background: #0a1628; padding: 16px 20px;
          display: flex; align-items: center; justify-content: space-between; flex-shrink: 0;
        }
        .chat-avatar-small {
          width: 32px; height: 32px; border-radius: 8px; background: #1a5ce4;
          display: flex; align-items: center; justify-content: center;
          font-size: 14px; font-weight: 700; color: #fff;
        }
        .chat-close { background: none; border: none; color: rgba(255,255,255,0.5); cursor: pointer; font-size: 20px; line-height: 1; transition: color 0.15s; }
        .chat-close:hover { color: #fff; }

        @media (max-width: 900px) {
          .hero { grid-template-columns: 1fr; padding: 48px 24px; }
          .services-strip { grid-template-columns: repeat(3,1fr); padding: 24px; }
          .why-grid, .doctors-grid { grid-template-columns: 1fr; }
          .footer-grid { grid-template-columns: 1fr; gap: 32px; }
          nav { padding: 0 24px; }
          .nav-center { display: none; }
          .top-bar { padding: 8px 24px; }
          .why-section, .doctors-section { padding: 48px 24px; }
          .lea-cta { padding: 56px 24px; }
          .footer-main { padding: 40px 24px 24px; }
          .launcher-text { display: none; }
          .launcher { padding: 14px; border-radius: 50%; }
        }
`

export default function HomePage() {
  const [chatOpen, setChatOpen] = useState(false)
  const router = useRouter()

  const noop = (e: React.MouseEvent) => e.preventDefault()

  return (
    <>
      <Head>
        <title>Lea Medical Center</title>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Playfair+Display:wght@600;700&display=swap" rel="stylesheet" />
      </Head>

      {/* Using dangerouslySetInnerHTML instead of a JSX text child avoids
          a server/client hydration text-mismatch: React reconciles a
          bare <style>{`...`}</style> tag's content as a text node, and
          large template literals can get processed slightly differently
          between the SSR pass and client hydration. Setting innerHTML
          directly bypasses that reconciliation entirely. */}
      <style dangerouslySetInnerHTML={{ __html: PAGE_STYLES }} />

      {/* Top bar */}
      <div className="top-bar">
        <div className="top-bar-left">
          <span>📍 825 Nicollet Mall, Minneapolis, MN</span>
          <span>🕐 Mon–Fri: 8am–6pm · Sat: 9am–2pm</span>
        </div>
        <div className="top-bar-right">Emergency: 1-800-LEA-HELP</div>
      </div>

      {/* Nav */}
      <nav>
        <a href="/" className="logo">
          <div className="logo-icon">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round">
              <path d="M12 2L12 22M2 12L22 12" />
            </svg>
          </div>
          <span className="logo-text">Lea Medical Center</span>
        </a>
        <div className="nav-center">
          <a href="#" onClick={noop}>Services</a>
          <a href="#" onClick={noop}>Doctors</a>
          <a href="#" onClick={noop}>Locations</a>
          <a href="#" onClick={noop}>About</a>
          <a href="#" onClick={noop}>Contact</a>
        </div>
        <div className="nav-right">
          <span className="nav-phone">📞 (416) 555-0192</span>
          <a href="/portal" style={{ background: 'transparent', border: '1.5px solid #e8edf5', color: '#0a1628', padding: '9px 18px', borderRadius: 8, fontSize: 13, fontWeight: 600, textDecoration: 'none', transition: 'all 0.15s' }}>Patient portal</a>
          <button className="btn-book" onClick={() => setChatOpen(true)}>Book appointment</button>
        </div>
      </nav>

      {/* Hero */}
      <section className="hero">
        <div>
          <div className="hero-label">⭐ Ranked #1 in Patient Satisfaction 2025</div>
          <h1>Your health is<br />our <em>priority</em></h1>
          <p className="hero-sub">
            Lea Medical Center provides world-class care across 12 specialties.
            Now with Lea's Health AI — book your appointment in under 90 seconds, insurance verified instantly.
          </p>
          <div className="hero-actions">
            <button className="btn-white" onClick={() => setChatOpen(true)}>Book appointment</button>
            <button className="btn-ghost">Learn more</button>
          </div>
        </div>

        <div className="hero-image">
        {[
        { img: 'https://randomuser.me/api/portraits/women/44.jpg', name: 'Dr. Sarah Patel', role: 'Family Medicine · 14 yrs' },
        { img: 'https://randomuser.me/api/portraits/men/32.jpg',   name: 'Dr. Michael Kim', role: 'Cardiology · 20 yrs' },
        { img: 'https://randomuser.me/api/portraits/women/68.jpg', name: 'Dr. Priya Santos', role: 'Mental Health · 11 yrs' },
        ].map((d, i) => (
        <div key={i} className="doctor-card">
            <img src={d.img} alt={d.name} style={{ width: 48, height: 48, borderRadius: '50%', objectFit: 'cover', flexShrink: 0 }} />
            <div className="doctor-info">
            <div className="doctor-name">{d.name}</div>
            <div className="doctor-role">{d.role}</div>
            </div>
            <div className="avail-badge">Available</div>
        </div>
        ))}
          <div className="hero-stats">
            <div className="hero-stat"><div className="hero-stat-num">55K+</div><div className="hero-stat-label">Patients</div></div>
            <div className="hero-stat"><div className="hero-stat-num">12</div><div className="hero-stat-label">Departments</div></div>
            <div className="hero-stat"><div className="hero-stat-num">98%</div><div className="hero-stat-label">Satisfaction</div></div>
          </div>
        </div>
      </section>

      {/* Services strip */}
      <div className="services-strip">
        {[
          { icon: '🏥', name: 'Family Medicine', sub: 'Primary care' },
          { icon: '❤️', name: 'Cardiology', sub: 'Heart health' },
          { icon: '🧠', name: 'Mental Health', sub: 'Psychiatry & therapy' },
          { icon: '🚑', name: 'Urgent Care', sub: 'Walk-in' },
          { icon: '👶', name: 'Pediatrics', sub: 'Child & teen care' },
          { icon: '🔬', name: 'Dermatology', sub: 'Skin health' },
        ].map((s, i) => (
          <div key={i} className="service-item">
            <div className="service-item-icon">{s.icon}</div>
            <div className="service-item-name">{s.name}</div>
            <div className="service-item-sub">{s.sub}</div>
          </div>
        ))}
      </div>

      {/* Why us */}
      <section className="why-section">
        <div className="section-eyebrow">Why Lea Medical Center</div>
        <h2 className="section-h2">Care you can trust, every visit</h2>
        <div className="why-grid">
          {[
            { icon: '⚡', title: 'AI-powered intake', desc: 'Lea\'s Health AI completes your registration in under 90 seconds — insurance verified, appointment booked, no paperwork.' },
            { icon: '🏆', title: 'Board-certified specialists', desc: 'Every physician at Lea Medical is board-certified with an average of 15 years of clinical experience.' },
            { icon: '🔒', title: 'HIPAA compliant', desc: 'Your health data is protected by enterprise-grade encryption and full HIPAA compliance at every step.' },
            { icon: '📱', title: 'Patient portal', desc: 'View your appointments, pay copays, and access your records anytime from any device.' },
            { icon: '⏱️', title: 'Short wait times', desc: 'Average wait time under 12 minutes. Real-time availability shown so you always know when your doctor is ready.' },
            { icon: '💊', title: 'Integrated care', desc: 'All your specialists share records so every provider has the full picture before you walk in the door.' },
          ].map((w, i) => (
            <div key={i} className="why-card">
              <div className="why-icon">{w.icon}</div>
              <div className="why-title">{w.title}</div>
              <div className="why-desc">{w.desc}</div>
            </div>
          ))}
        </div>
      </section>

      {/* Doctors */}
      <section className="doctors-section">
        <div className="doctors-inner">
          <div className="section-eyebrow">Our team</div>
          <h2 className="section-h2">Meet our physicians</h2>
          <div className="doctors-grid">
            {[
              { img: 'https://randomuser.me/api/portraits/women/44.jpg', name: 'Dr. Sarah Patel', specialty: 'Family Medicine', exp: '14 years experience' },
              { img: 'https://randomuser.me/api/portraits/men/32.jpg', name: 'Dr. Michael Kim', specialty: 'Cardiology', exp: '20 years experience' },
              { img: 'https://randomuser.me/api/portraits/women/68.jpg', name: 'Dr. Priya Santos', specialty: 'Mental Health', exp: '11 years experience' },
              { img: 'https://randomuser.me/api/portraits/women/67.jpg', name: 'Dr. Emily Wong', specialty: 'Pediatrics', exp: '9 years experience' },
            ].map((d, i) => (
              <div key={i} className="doc-card">
                <img src={d.img} alt={d.name} style={{ width: 72, height: 72, borderRadius: '50%', objectFit: 'cover', margin: '0 auto 14px', display: 'block' }} />
                <div className="doc-name">{d.name}</div>
                <div className="doc-specialty">{d.specialty}</div>
                <div className="doc-exp">{d.exp}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Lea's Health CTA */}
      <section className="lea-cta">
        <div className="lea-cta-tag">✨ Powered by Lea's Health AI</div>
        <h2>Book your appointment in 90 seconds</h2>
        <p className="lea-cta-sub">No phone calls. No paperwork. Insurance verified instantly.<br />Just tell Lea's Health why you're coming in.</p>
        <div className="lea-cta-actions">
          <button className="btn-white" style={{ padding: '14px 32px', fontSize: 15 }} onClick={() => setChatOpen(true)}>
            Start intake now →
          </button>
          <a href="/portal" style={{ background: 'rgba(255,255,255,0.1)', color: '#fff', border: '1.5px solid rgba(255,255,255,0.25)', padding: '14px 32px', borderRadius: 10, fontSize: 15, fontWeight: 500, textDecoration: 'none' }}>
            Patient portal
          </a>
        </div>
      </section>

      {/* Footer */}
      <footer className="footer-main">
        <div className="footer-grid">
          <div className="footer-brand">
            <div className="footer-logo-text">
              <div className="footer-logo-icon">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round">
                  <path d="M12 2L12 22M2 12L22 12" />
                </svg>
              </div>
              Lea Medical Center
            </div>
            <div className="footer-tagline">World-class healthcare powered by compassionate staff and cutting-edge AI intake technology.</div>
          </div>
          <div className="footer-col">
            <h4>Services</h4>
            <a href="#">Family Medicine</a>
            <a href="#">Cardiology</a>
            <a href="#">Mental Health</a>
            <a href="#">Urgent Care</a>
            <a href="#">Pediatrics</a>
          </div>
          <div className="footer-col">
            <h4>Patients</h4>
            <a href="/portal">Patient portal</a>
            <a href="#">Medical records</a>
            <a href="#">Insurance</a>
            <a href="#">Billing</a>
          </div>
          <div className="footer-col">
            <h4>Contact</h4>
            <a href="#">123 Medical Drive</a>
            <a href="#">Toronto, ON M5V 1A1</a>
            <a href="#">(416) 555-0192</a>
            <a href="#">info@leamedical.com</a>
          </div>
        </div>
        <div className="footer-bottom">
          <div className="footer-bottom-text">© 2026 Lea Medical Center · HIPAA Compliant · All rights reserved</div>
          <div className="footer-bottom-text">Privacy Policy · Terms of Service · Accessibility</div>
        </div>
      </footer>

      {/* Chat launcher */}
      <button className="launcher" onClick={() => setChatOpen(true)}>
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
        </svg>
        <span className="launcher-text">Talk to Lea's Health</span>
        <div className="launcher-badge">1</div>
      </button>

      {/* Chat modal */}
      {chatOpen && (
        <div className="chat-overlay" onClick={e => { if (e.target === e.currentTarget) setChatOpen(false) }}>
          <div className="chat-modal">
            <div className="chat-header">
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <div className="chat-avatar-small">L</div>
                <div>
                  <div style={{ fontSize: 15, fontWeight: 600, color: '#fff' }}>Lea's Health</div>
                  <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.5)', marginTop: 1 }}>AI patient intake · Lea Medical Center</div>
                </div>
              </div>
              <button className="chat-close" onClick={() => setChatOpen(false)}>✕</button>
            </div>
            <iframe src="/intake" style={{ flex: 1, border: 'none', width: '100%' }} title="Lea's Health Intake" />
          </div>
        </div>
      )}
    </>
  )
}