"use client";

import { useCallback, useEffect, useState } from "react";
import { EmailLogin } from "@/components/auth/EmailLogin";
import { BookingSidebar, type ChatSelection } from "@/components/bookings/BookingSidebar";
import { ReceptionChat } from "@/components/chat/ReceptionChat";
import {
  clearToken,
  fetchBookings,
  fetchMe,
  loadToken,
  saveToken,
  type Account,
  type BookingLists,
} from "@/lib/api";

const emptyBookings: BookingLists = { active: [], past: [] };

export function ReceptionApp() {
  const [token, setToken] = useState<string | null>(null);
  const [user, setUser] = useState<Account | null>(null);
  const [ready, setReady] = useState(false);
  const [bookings, setBookings] = useState<BookingLists>(emptyBookings);
  const [selection, setSelection] = useState<ChatSelection>({ kind: "new" });
  const [chatNonce, setChatNonce] = useState(0);

  const refreshBookings = useCallback(async (nextToken: string) => {
    try {
      setBookings(await fetchBookings(nextToken));
    } catch {
      setBookings(emptyBookings);
    }
  }, []);

  useEffect(() => {
    const stored = loadToken();
    if (!stored) {
      setReady(true);
      return;
    }
    fetchMe(stored)
      .then((account) => {
        setToken(stored);
        setUser(account);
        return refreshBookings(stored);
      })
      .catch(() => {
        clearToken();
      })
      .finally(() => setReady(true));
  }, [refreshBookings]);

  useEffect(() => {
    if (selection.kind !== "active") return;
    const conversationId = selection.booking.conversation_id;
    const stillActive = bookings.active.some(
      (booking) => booking.conversation_id === conversationId,
    );
    if (stillActive || conversationId == null) return;
    const moved = bookings.past.find((booking) => booking.conversation_id === conversationId);
    if (moved) setSelection({ kind: "past", booking: moved });
  }, [bookings, selection]);

  function handleSelect(next: ChatSelection) {
    if (next.kind === "new") setChatNonce((value) => value + 1);
    setSelection(next);
  }

  function handleLogout() {
    clearToken();
    setToken(null);
    setUser(null);
    setBookings(emptyBookings);
    setSelection({ kind: "new" });
  }

  if (!ready) {
    return (
      <main className="kk-sign-in">
        <p>Opening reception…</p>
      </main>
    );
  }

  if (!token || !user) {
    return (
      <EmailLogin
        onSignedIn={(nextToken, account) => {
          saveToken(nextToken);
          setToken(nextToken);
          setUser(account);
          setSelection({ kind: "new" });
          void refreshBookings(nextToken);
        }}
      />
    );
  }

  const chatKey =
    selection.kind === "new"
      ? "new"
      : `${selection.kind}-${selection.booking.conversation_id ?? selection.booking.booking_id}`;

  return (
    <ReceptionChat
      key={selection.kind === "new" ? `new-${chatNonce}` : chatKey}
      token={token}
      mode={selection.kind === "past" ? "past" : selection.kind === "active" ? "active" : "new"}
      conversationId={selection.kind === "new" ? null : selection.booking.conversation_id}
      onBookingsChanged={() => {
        void refreshBookings(token);
      }}
      sidebar={
        <BookingSidebar
          bookings={bookings}
          selection={selection}
          name={user.name}
          email={user.email}
          onLogout={handleLogout}
          onSelect={handleSelect}
        />
      }
    />
  );
}
