import Link from "next/link";

function SparkleIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className="kk-icon">
      <path d="M12 2.8 14.4 9.6 21.2 12l-6.8 2.4L12 21.2l-2.4-6.8L2.8 12l6.8-2.4L12 2.8Z" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
      <path d="m19 2 .8 2.2L22 5l-2.2.8L19 8l-.8-2.2L16 5l2.2-.8L19 2Z" fill="currentColor" />
    </svg>
  );
}

function ArrowIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className="kk-icon">
      <path d="M4.5 12h14m-5.5-5.5 5.5 5.5-5.5 5.5" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export default function Home() {
  return (
    <main className="kk-shell">
      <div className="kk-container">
        <nav className="kk-nav" aria-label="Main navigation">
          <Link href="/" className="kk-brand" aria-label="Kesh Kala home">
            <span className="kk-mark">क</span>
            <span>
              <span className="kk-brand-name">Kesh Kala</span>
              <span className="kk-brand-sub">Salon · Grooming · Care</span>
            </span>
          </Link>
          <div className="kk-nav-links">
            <a className="kk-nav-link" href="#experience">The experience</a>
            <a className="kk-nav-link" href="#services">Our services</a>
          </div>
          <Link href="/reception" className="kk-nav-cta">
            Talk to Tara <ArrowIcon />
          </Link>
        </nav>

        <section className="kk-hero">
          <div className="kk-hero-copy">
            <div className="kk-eyebrow"><SparkleIcon /> A more personal salon experience</div>
            <h1 className="kk-headline">
              Good style.<br />
              <em>No guesswork.</em>
            </h1>
            <p className="kk-copy">
              Your next fresh look starts with a simple conversation. Tell Tara what you have in mind, explore services, and find an appointment that fits your day.
            </p>
            <div className="kk-actions">
              <Link href="/reception" className="kk-primary">
                <span className="kk-primary-mic" aria-hidden="true">◖</span>
                Start a conversation <ArrowIcon />
              </Link>
              <a href="#experience" className="kk-secondary">See how it works</a>
            </div>
            <div className="kk-social-proof">
              <div className="kk-avatar-stack" aria-hidden="true">
                <span className="kk-avatar">क</span><span className="kk-avatar">T</span><span className="kk-avatar">✦</span>
              </div>
              <span>Speak naturally. We’ll take it from there.</span>
            </div>
          </div>

          <div className="kk-visual" aria-label="A calm, contemporary salon experience">
            <div className="kk-orbit" />
            <div className="kk-portrait" role="img" aria-label="Warm contemporary salon interior">
              <div className="kk-portrait-shade" />
              <div className="kk-portrait-caption"><span>THE KESH KALA EDIT</span><strong>Your time. Your style.</strong></div>
            </div>
            <div className="kk-float-card kk-float-one">
              <span className="kk-float-icon">✳</span>
              <span><strong>A little help, any time</strong><small>Your personal salon receptionist</small></span>
            </div>
            <div className="kk-float-card kk-float-two">
              <span className="kk-float-check">✓</span>
              <span><strong>Easy appointment planning</strong><small>Services, slots and details in one chat</small></span>
            </div>
            <span className="kk-orbit-label">Aapka style. Aapka waqt.</span>
          </div>
        </section>

        <section className="kk-feature-section" id="experience">
          <div className="kk-section-heading">
            <div><span className="kk-eyebrow">The Kesh Kala experience</span><h2>Salon planning, made simple.</h2></div>
            <p>No forms to figure out. Just tell Tara what you need, in your own words.</p>
          </div>
          <div className="kk-feature-grid">
            <article className="kk-feature-card">
              <span className="kk-feature-number">01 / DISCOVER</span>
              <span className="kk-feature-icon">✂</span>
              <h3>Find your service</h3>
              <p>Explore haircuts, beard styling, grooming combos and care services without digging through menus.</p>
            </article>
            <article className="kk-feature-card">
              <span className="kk-feature-number">02 / PERSONALISE</span>
              <span className="kk-feature-icon">✦</span>
              <h3>Make it yours</h3>
              <p>Choose the services you want, ask questions, and build your visit at your own pace.</p>
            </article>
            <article className="kk-feature-card" id="services">
              <span className="kk-feature-number">03 / BOOK</span>
              <span className="kk-feature-icon">◷</span>
              <h3>Pick your time</h3>
              <p>Check available appointment slots and confirm only when all the details feel right.</p>
            </article>
          </div>
        </section>

        <section className="kk-bottom-cta">
          <div><span className="kk-eyebrow">Ready when you are</span><h2>Let’s get you feeling fresh.</h2></div>
          <Link href="/reception" className="kk-primary">Meet Tara <ArrowIcon /></Link>
        </section>

        <footer className="kk-footer">
          <Link href="/" className="kk-brand kk-footer-brand"><span className="kk-mark">क</span><span className="kk-brand-name">Kesh Kala</span></Link>
          <span>Thoughtful grooming. Simpler bookings.</span>
          <span>Made for your everyday.</span>
        </footer>
      </div>
    </main>
  );
}
