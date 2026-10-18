"use client";

import Link from "next/link";
import type { BookingSummary } from "@/lib/api";

export type ChatSelection =
  | { kind: "new" }
  | { kind: "active" | "past"; booking: BookingSummary };

type BookingSidebarProps = {
  bookings: { active: BookingSummary[]; past: BookingSummary[] };
  selection: ChatSelection;
  name: string;
  email: string;
  onLogout: () => void;
  onSelect: (selection: ChatSelection) => void;
};

export function BookingSidebar({
  bookings,
  selection,
  name,
  email,
  onLogout,
  onSelect,
}: BookingSidebarProps) {
  const selectedId = selection.kind === "new" ? null : selection.booking.conversation_id;
  const initial = name.trim().charAt(0).toUpperCase() || "K";

  return (
    <aside className="kk-sidebar" aria-label="Your appointments">
      <div className="kk-sidebar-scroll">
        <button type="button" className="kk-new-chat" onClick={() => onSelect({ kind: "new" })}>
          <span aria-hidden="true">＋</span> New chat
        </button>
        <BookingGroup
          title="Active"
          empty="No upcoming appointments."
          icon="✦"
          items={bookings.active}
          selectedId={selection.kind === "active" ? selectedId : null}
          onSelect={(booking) => onSelect({ kind: "active", booking })}
        />
        <BookingGroup
          title="Past"
          empty="No past appointments yet."
          icon="◷"
          items={bookings.past}
          selectedId={selection.kind === "past" ? selectedId : null}
          onSelect={(booking) => onSelect({ kind: "past", booking })}
        />
      </div>
      <div className="kk-sidebar-footer">
        <Link href="/" className="kk-sidebar-home">
          <span aria-hidden="true">←</span> Back home
        </Link>
        <div className="kk-profile-card">
          <span className="kk-profile-avatar">{initial}</span>
          <span className="kk-profile-copy">
            <strong>{name}</strong>
            <small>{email}</small>
          </span>
          <button type="button" className="kk-logout-link" onClick={onLogout} aria-label="Log out" title="Log out">
            ↗
          </button>
        </div>
      </div>
    </aside>
  );
}

function BookingGroup({
  title,
  empty,
  icon,
  items,
  selectedId,
  onSelect,
}: {
  title: string;
  empty: string;
  icon: string;
  items: BookingSummary[];
  selectedId: number | null;
  onSelect: (booking: BookingSummary) => void;
}) {
  return (
    <section className="kk-sidebar-section">
      <p className="kk-sidebar-label">{title}</p>
      {items.length === 0 ? (
        <div className="kk-history-empty">
          <span aria-hidden="true">{icon}</span>
          <p>{empty}</p>
        </div>
      ) : (
        <ul className="kk-session-list">
          {items.map((booking) => {
            const selected = booking.conversation_id === selectedId && selectedId !== null;
            const services = booking.services.length ? booking.services.join(", ") : "Appointment";
            return (
              <li key={booking.booking_id}>
                <button
                  type="button"
                  className={`kk-session-card ${selected ? "is-current" : ""}`}
                  onClick={() => onSelect(booking)}
                >
                  <span className="kk-session-icon" aria-hidden="true">{icon}</span>
                  <span className="kk-session-copy">
                    <strong>
                      {booking.staff_name} · {booking.time}
                    </strong>
                    <small>
                      {booking.date}
                      {booking.status === "cancelled" ? " · Cancelled" : ""}
                    </small>
                    <span>{services}</span>
                  </span>
                  {selected ? <span className="kk-current-indicator" aria-hidden="true" /> : null}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
