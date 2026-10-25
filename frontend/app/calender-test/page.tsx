"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { API_URL } from "@/lib/api";

type StaffRow = {
  staff_id: string;
  name: string;
  calendar_id: string;
};

type BusyBlock = {
  start: string;
  end: string;
};

type CreatedEvent = {
  event_id: string;
  summary: string;
  html_link?: string;
  staff_id: string;
};

const DEFAULT_STAFF = "ST01";
const DEFAULT_DATE = "2026-10-24";
const DEFAULT_TIME = "14:00";
const DEFAULT_DURATION = 60;
const DEFAULT_TITLE = "Calendar test";

function clock(value: string) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat("en-IN", {
    timeZone: "Asia/Kolkata",
    hour: "numeric",
    minute: "2-digit",
  }).format(parsed);
}

async function readJson<T>(path: string, options?: RequestInit): Promise<T> {
  const headers = new Headers(options?.headers);
  if (options?.body) headers.set("Content-Type", "application/json");
  const response = await fetch(`${API_URL}${path}`, { ...options, headers });
  const data = (await response.json().catch(() => ({}))) as { detail?: unknown };
  if (!response.ok) {
    throw new Error(typeof data.detail === "string" ? data.detail : "Calendar request failed.");
  }
  return data as T;
}

export default function CalenderTestPage() {
  const [staff, setStaff] = useState<StaffRow[]>([]);
  const [staffId, setStaffId] = useState(DEFAULT_STAFF);
  const [date, setDate] = useState(DEFAULT_DATE);
  const [time, setTime] = useState(DEFAULT_TIME);
  const [duration, setDuration] = useState(DEFAULT_DURATION);
  const [title, setTitle] = useState(DEFAULT_TITLE);
  const [busy, setBusy] = useState<BusyBlock[] | null>(null);
  const [created, setCreated] = useState<CreatedEvent[]>([]);
  const [error, setError] = useState("");
  const [pending, setPending] = useState<"staff" | "busy" | "create" | "delete" | null>(null);

  useEffect(() => {
    let cancelled = false;
    setPending("staff");
    readJson<{ staff: StaffRow[] }>("/api/calender-test/staff")
      .then((data) => {
        if (cancelled) return;
        setStaff(data.staff);
        if (!data.staff.some((row) => row.staff_id === DEFAULT_STAFF) && data.staff[0]) {
          setStaffId(data.staff[0].staff_id);
        }
      })
      .catch((caught: Error) => {
        if (!cancelled) setError(caught.message || "Could not load staff calendars.");
      })
      .finally(() => {
        if (!cancelled) setPending((current) => (current === "staff" ? null : current));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const selected = staff.find((row) => row.staff_id === staffId);

  async function showBusy() {
    setPending("busy");
    setError("");
    try {
      const data = await readJson<{ busy: BusyBlock[] }>(
        `/api/calender-test/busy?staff_id=${encodeURIComponent(staffId)}&date=${encodeURIComponent(date)}`,
      );
      setBusy(data.busy);
    } catch (caught) {
      const reason = caught as Error;
      setError(reason.message || "Could not read that calendar.");
    } finally {
      setPending(null);
    }
  }

  async function createEvent() {
    setPending("create");
    setError("");
    try {
      const event = await readJson<CreatedEvent>("/api/calender-test/events", {
        method: "POST",
        body: JSON.stringify({
          staff_id: staffId,
          date,
          time,
          duration_min: duration,
          title,
        }),
      });
      setCreated((current) => [{ ...event, staff_id: staffId }, ...current]);
      await showBusy();
    } catch (caught) {
      const reason = caught as Error;
      setError(reason.message || "Could not create the test event.");
      setPending(null);
    }
  }

  async function removeEvent(event: CreatedEvent) {
    setPending("delete");
    setError("");
    try {
      await readJson<{ deleted: string }>(
        `/api/calender-test/events/${encodeURIComponent(event.event_id)}?staff_id=${encodeURIComponent(event.staff_id)}`,
        { method: "DELETE" },
      );
      setCreated((current) => current.filter((item) => item.event_id !== event.event_id));
      if (event.staff_id === staffId) await showBusy();
      else setPending(null);
    } catch (caught) {
      const reason = caught as Error;
      setError(reason.message || "Could not delete that event.");
      setPending(null);
    }
  }

  return (
    <main className="kk-cal-page">
      <section className="kk-cal-card">
        <Link href="/" className="kk-back-link">
          <span aria-hidden="true">←</span> Back home
        </Link>
        <p className="kk-eyebrow" style={{ marginTop: 18 }}>
          Calendar test
        </p>
        <h1>Staff calendars</h1>
        <p>
          Writes a visit onto one stylist calendar between 10:00 AM and 8:00 PM. A second visit
          that overlaps that stylist is refused. Reception booking still uses the database slots.
        </p>

        {error && (
          <p role="alert" className="kk-error-message" style={{ marginTop: 16 }}>
            <span aria-hidden="true">!</span>
            {error}
          </p>
        )}

        <div className="kk-cal-grid">
          <label>
            Stylist
            <select value={staffId} onChange={(event) => setStaffId(event.target.value)}>
              {staff.length === 0 && <option value={DEFAULT_STAFF}>Rahul</option>}
              {staff.map((row) => (
                <option key={row.staff_id} value={row.staff_id}>
                  {row.name}
                  {row.calendar_id ? "" : " (no calendar id)"}
                </option>
              ))}
            </select>
          </label>
          <label>
            Date
            <input type="date" value={date} onChange={(event) => setDate(event.target.value)} />
          </label>
          <label>
            Start
            <input
              type="time"
              min="10:00"
              max="20:00"
              value={time}
              onChange={(event) => setTime(event.target.value)}
            />
          </label>
          <label>
            Duration (minutes)
            <input
              type="number"
              min={15}
              step={15}
              value={duration}
              onChange={(event) => setDuration(Number(event.target.value) || DEFAULT_DURATION)}
            />
          </label>
        </div>
        <label>
          Title
          <input value={title} onChange={(event) => setTitle(event.target.value)} />
        </label>

        <div className="kk-cal-actions">
          <button type="button" className="kk-secondary" onClick={() => void showBusy()} disabled={pending !== null}>
            {pending === "busy" ? "Reading calendar…" : "Show busy"}
          </button>
          <button type="button" className="kk-primary" onClick={() => void createEvent()} disabled={pending !== null}>
            {pending === "create" ? "Creating…" : "Create test event"}
          </button>
        </div>

        <section className="kk-cal-section">
          <h2>Busy on {selected?.name || "Rahul"}</h2>
          {busy === null ? (
            <p className="kk-cal-empty">No lookup yet. Show busy uses the stylist and date above.</p>
          ) : busy.length === 0 ? (
            <p className="kk-cal-empty">Nothing is booked on this calendar for {date}.</p>
          ) : (
            <ul className="kk-cal-list">
              {busy.map((block) => (
                <li key={`${block.start}-${block.end}`}>
                  <span>
                    <strong>
                      {clock(block.start)} – {clock(block.end)}
                    </strong>
                    <small>{date}</small>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="kk-cal-section">
          <h2>Events created here</h2>
          {created.length === 0 ? (
            <p className="kk-cal-empty">
              Create test event writes “{title || DEFAULT_TITLE}” at {time} for {duration} minutes on {date}.
            </p>
          ) : (
            <ul className="kk-cal-list">
              {created.map((event) => {
                const owner = staff.find((row) => row.staff_id === event.staff_id);
                return (
                  <li key={event.event_id}>
                    <span>
                      <strong>{event.summary || DEFAULT_TITLE}</strong>
                      <small>
                        {owner?.name || event.staff_id}
                        {event.html_link ? " · " : ""}
                        {event.html_link ? (
                          <a href={event.html_link} target="_blank" rel="noreferrer">
                            Open in Google Calendar
                          </a>
                        ) : null}
                      </small>
                    </span>
                    <button
                      type="button"
                      className="kk-text-button"
                      onClick={() => void removeEvent(event)}
                      disabled={pending !== null}
                    >
                      {pending === "delete" ? "Deleting…" : "Delete"}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      </section>
    </main>
  );
}
