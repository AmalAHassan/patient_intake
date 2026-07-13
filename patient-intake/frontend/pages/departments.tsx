import { useState } from 'react'
import Head from 'next/head'
import { useRouter } from 'next/router'

const DEPARTMENTS = [
  { icon: '🏥', name: 'Family Medicine',  desc: 'Primary care for every stage of life. Annual checkups, chronic disease management, vaccinations, and preventive care for the whole family.', doctors: ['Dr. Sarah Patel', 'Dr. James Chen'], wait: '3 slots today' },
  { icon: '❤️', name: 'Cardiology',       desc: 'Comprehensive heart health services including echocardiograms, stress tests, Holter monitoring, and preventive cardiovascular care.', doctors: ['Dr. Michael Kim', 'Dr. Angela Torres'], wait: '1 slot today' },
  { icon: '🧠', name: 'Mental Health',    desc: 'Therapy, psychiatry, and crisis support for adults and adolescents. Confidential, evidence-based care for anxiety, depression, PTSD, and more.', doctors: ['Dr. Priya Santos', 'Dr. David Adams'], wait: '5 slots today' },
  { icon: '🚑', name: 'Urgent Care',      desc: 'Walk-in care for non-life-threatening conditions. Cuts, infections, sprains, fevers, and minor injuries treated quickly without an appointment.', doctors: ['Dr. Lisa Rivera', 'Dr. Omar Hassan'], wait: 'Open now' },
  { icon: '👶', name: 'Pediatrics',       desc: 'Specialized care for infants, children, and adolescents up to age 18. Growth tracking, vaccinations, developmental screenings, and sick visits.', doctors: ['Dr. Emily Wong', 'Dr. Carlos Mendez'], wait: '2 slots today' },
  { icon: '🔬', name: 'Dermatology',      desc: 'Skin health for all ages. Acne, eczema, psoriasis, mole checks, skin cancer screenings, and cosmetic procedures by board-certified dermatologists.', doctors: ['Dr. Rachel Green', 'Dr. Amir Shah'], wait: '4 slots today' },
  { icon: '🦴', name: 'Orthopedics',      desc: 'Bone, joint, and muscle care. Sports injuries, fractures, arthritis, spinal conditions, and joint replacement surgery consultations.', doctors: ['Dr. Kevin Park', 'Dr. Natalie Brooks'], wait: '2 slots today' },
  { icon: '👁️', name: 'Ophthalmology',    desc: 'Eye health and vision care. Routine eye exams, cataract evaluation, glaucoma screening, diabetic eye disease, and corrective lens prescriptions.', doctors: ['Dr. Susan Lee', 'Dr. Thomas Wright'], wait: '3 slots today' },
  { icon: '🫁', name: 'Pulmonology',       desc: 'Respiratory health for asthma, COPD, sleep apnea, and chronic lung conditions. Pulmonary function testing and bronchoscopy available.', doctors: ['Dr. Mark Johnson', 'Dr. Fatima Al-Rashid'], wait: '2 slots today' },
]

export default function DepartmentsPage() {
  const [chatOpen, setChatOpen] = useState(false)
  const [selected, setSelected] = useState<number | null>(null)
  const router = useRouter()

  return (
    <>
      <Head>
        <title>Departments — Lea Medical Center</title>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Playfair+Display:wght@600;700&display=swap" rel="stylesheet" />
      </Head>

      <style>{`
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: 'Inter', sans-serif; background: #fafbff; color: #0a1628; }

        nav {
          position: sticky; top: 0; z-index: 100;
          background: rgba(255,255,255,0.97); backdrop-filter: blur(8px);
          border-bottom: 1px solid #e8edf5;
          padding: 0 56px; display: flex; align-items: center;
          justify-content: space-between; height: 68px;
        }
        .nav-logo {
          display: flex; align-items: center; gap: 10px;
          font-size: 18px; font-weight: 700; color: #0a1628; text-decoration: none;
        }
        .nav-logo-icon {
          width: 32px; height: 32px; border-radius: 8px;
          background: #1a5ce4; display: flex; align-items: center; justify-content: center;
        }
        .nav-links { display: flex; align-items: center; gap: 28px; }
        .nav-links a { font-size: 14px; color: #4a5568; text-decoration: none; font-weight: 500; transition: color 0.15s; }
        .nav-links a:hover, .nav-links a.active { color: #1a5ce4; }
        .nav-cta { background: #1a5ce4 !important; color: #fff !important; padding: 9px 20px; border-radius: 8px; font-size: 13px !important; font-weight: 600 !important; }
        .nav-cta:hover { background: #1449c0 !important; }

        .page-header {
          background: #fff; border-bottom: 1px solid #e8edf5;
          padding: 40px 56px;
        }
        .breadcrumb { font-size: 13px; color: #718096; margin-bottom: 12px; }
        .breadcrumb a { color: #1a5ce4; text-decoration: none; }
        .page-title {
          font-family: 'Playfair Display', serif;
          font-size: 36px; font-weight: 700; color: #0a1628; margin-bottom: 8px;
        }
        .page-sub { font-size: 15px; color: #4a5568; }

        .content {
          max-width: 1200px; margin: 0 auto;
          padding: 48px 56px;
          display: grid; grid-template-columns: 1fr 360px; gap: 32px; align-items: start;
        }
        .dept-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
        .dept-card {
          background: #fff; border-radius: 14px;
          border: 1.5px solid #e8edf5; padding: 22px;
          cursor: pointer; transition: all 0.15s;
        }
        .dept-card:hover { border-color: #1a5ce4; box-shadow: 0 4px 16px rgba(26,92,228,0.08); }
        .dept-card.selected { border-color: #1a5ce4; background: #f0f5ff; box-shadow: 0 4px 16px rgba(26,92,228,0.12); }
        .dept-icon {
          width: 44px; height: 44px; border-radius: 10px;
          background: #f0f5ff; display: flex; align-items: center;
          justify-content: center; font-size: 20px; margin-bottom: 12px;
        }
        .dept-name { font-size: 14px; font-weight: 600; color: #0a1628; margin-bottom: 6px; }
        .dept-desc { font-size: 12px; color: #718096; line-height: 1.6; margin-bottom: 10px; }
        .dept-wait {
          display: inline-flex; align-items: center; gap: 5px;
          font-size: 11px; font-weight: 600; color: #1a7f3c;
          background: #f0faf4; border-radius: 20px; padding: 3px 9px;
        }
        .wait-dot { width: 5px; height: 5px; border-radius: 50%; background: #22c55e; }

        .sidebar { position: sticky; top: 96px; }
        .sidebar-card {
          background: #fff; border-radius: 16px;
          border: 1px solid #e8edf5; padding: 24px; margin-bottom: 16px;
          box-shadow: 0 4px 16px rgba(26,92,228,0.06);
        }
        .sidebar-title { font-size: 16px; font-weight: 600; color: #0a1628; margin-bottom: 4px; }
        .sidebar-sub { font-size: 13px; color: #718096; margin-bottom: 16px; }
        .btn-blue {
          background: #1a5ce4; color: #fff; width: 100%;
          padding: 12px; border-radius: 10px; border: none;
          font-family: 'Inter', sans-serif; font-size: 14px; font-weight: 600;
          cursor: pointer; transition: background 0.15s; margin-bottom: 8px;
        }
        .btn-blue:hover { background: #1449c0; }
        .btn-outline {
          background: transparent; color: #0a1628; width: 100%;
          padding: 12px; border-radius: 10px; border: 1.5px solid #e8edf5;
          font-family: 'Inter', sans-serif; font-size: 14px; font-weight: 500;
          cursor: pointer; transition: all 0.15s;
        }
        .btn-outline:hover { border-color: #1a5ce4; color: #1a5ce4; }

        .doctor-list { margin-top: 12px; }
        .doctor-item {
          display: flex; align-items: center; gap: 10px;
          padding: 8px 0; border-bottom: 1px solid #f0f4fb;
        }
        .doctor-item:last-child { border-bottom: none; }
        .doctor-avatar {
          width: 32px; height: 32px; border-radius: 50%;
          background: #e8f0fe; display: flex; align-items: center;
          justify-content: center; font-size: 12px; font-weight: 600; color: #1a5ce4;
          flex-shrink: 0;
        }
        .doctor-name { font-size: 13px; font-weight: 500; color: #0a1628; }

        .portal-card {
          background: #0a1628; border-radius: 16px; padding: 24px;
        }
        .portal-title { font-size: 15px; font-weight: 600; color: #fff; margin-bottom: 6px; }
        .portal-sub { font-size: 13px; color: rgba(255,255,255,0.5); margin-bottom: 16px; line-height: 1.5; }
        .btn-white {
          background: #fff; color: #0a1628; width: 100%;
          padding: 11px; border-radius: 10px; border: none;
          font-family: 'Inter', sans-serif; font-size: 14px; font-weight: 600;
          cursor: pointer; transition: opacity 0.15s;
        }
        .btn-white:hover { opacity: 0.9; }

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
        .chat-avatar {
          width: 32px; height: 32px; border-radius: 8px; background: #1a5ce4;
          display: flex; align-items: center; justify-content: center;
          font-size: 14px; font-weight: 700; color: #fff; font-family: 'Playfair Display', serif;
        }
        .chat-close { background: none; border: none; color: rgba(255,255,255,0.5); cursor: pointer; font-size: 20px; }
        .chat-close:hover { color: #fff; }

        @media (max-width: 900px) {
          .content { grid-template-columns: 1fr; padding: 32px 24px; }
          .dept-grid { grid-template-columns: 1fr; }
          .sidebar { position: static; }
          nav { padding: 0 24px; }
          .nav-links a:not(.nav-cta) { display: none; }
          .page-header { padding: 32px 24px; }
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
          <a href="/departments" className="active">Departments</a>
          <a href="#">Providers</a>
          <a href="#">Locations</a>
          <a href="/portal">Patient portal</a>
          <a href="#" className="nav-cta" onClick={e => { e.preventDefault(); setChatOpen(true) }}>Book appointment</a>
        </div>
      </nav>

      {/* Page header */}
      <div className="page-header">
        <div className="breadcrumb"><a href="/">Home</a> › Departments</div>
        <div className="page-title">Our Departments</div>
        <div className="page-sub">Select a department to learn more and book with Lea Health AI.</div>
      </div>

      {/* Content */}
      <div className="content">
        <div>
          <div className="dept-grid">
            {DEPARTMENTS.map((d, i) => (
              <div
                key={i}
                className={`dept-card${selected === i ? ' selected' : ''}`}
                onClick={() => setSelected(i)}
              >
                <div className="dept-icon">{d.icon}</div>
                <div className="dept-name">{d.name}</div>
                <div className="dept-desc">{d.desc}</div>
                <div className="dept-wait"><div className="wait-dot" />{d.wait}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Sidebar */}
        <div className="sidebar">
          <div className="sidebar-card">
            {selected !== null ? (
              <>
                <div className="sidebar-title">{DEPARTMENTS[selected].name}</div>
                <div className="sidebar-sub">{DEPARTMENTS[selected].wait} available</div>
                <button className="btn-blue" onClick={() => setChatOpen(true)}>
                  Book with Lea Health →
                </button>
                <button className="btn-outline" onClick={() => setChatOpen(true)}>
                  Learn more
                </button>
                <div className="doctor-list">
                  <div style={{ fontSize: 11, fontWeight: 600, color: '#718096', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 8 }}>Providers</div>
                  {DEPARTMENTS[selected].doctors.map((doc, i) => (
                    <div key={i} className="doctor-item">
                      <div className="doctor-avatar">{doc.split(' ').slice(-1)[0][0]}</div>
                      <div className="doctor-name">{doc}</div>
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <>
                <div className="sidebar-title">Book an appointment</div>
                <div className="sidebar-sub">Select a department on the left, or start intake with Lea Health now.</div>
                <button className="btn-blue" onClick={() => setChatOpen(true)}>Start with Lea Health →</button>
              </>
            )}
          </div>

          <div className="portal-card">
            <div className="portal-title">Patient portal</div>
            <div className="portal-sub">View your appointments, pay copays, and access your health records.</div>
            <button className="btn-white" onClick={() => router.push('/portal')}>Open portal →</button>
          </div>
        </div>
      </div>

      {/* Chat modal */}
      {chatOpen && (
        <div className="chat-overlay" onClick={e => { if (e.target === e.currentTarget) setChatOpen(false) }}>
          <div className="chat-modal">
            <div className="chat-header">
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <div className="chat-avatar">L</div>
                <div>
                  <div style={{ fontSize: 15, fontWeight: 600, color: '#fff' }}>Lea Health</div>
                  <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.5)', marginTop: 1 }}>
                    {selected !== null ? DEPARTMENTS[selected].name : 'AI patient intake'} · Lea Medical Center
                  </div>
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