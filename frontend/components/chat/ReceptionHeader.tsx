import Link from "next/link";

export function ReceptionHeader() {
  return (
    <header className="kk-chat-nav">
      <Link href="/" className="kk-brand" aria-label="Kesh Kala home">
        <span className="kk-mark">क</span>
        <span>
          <span className="kk-brand-name">Kesh Kala</span>
          <span className="kk-brand-sub">Salon · Grooming · Care</span>
        </span>
      </Link>
      <span className="kk-topbar-note">YOUR PERSONAL SALON ASSISTANT</span>
    </header>
  );
}
