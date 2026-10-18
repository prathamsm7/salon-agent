"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { ChatComposer } from "@/components/chat/ChatComposer";
import { MessageList } from "@/components/chat/MessageList";
import { ReceptionHeader } from "@/components/chat/ReceptionHeader";
import type { ChatMessage, SessionStatus } from "@/components/chat/types";
import {
  appendTranscript,
  insertChoiceList,
  microphoneError,
  statusLabel,
} from "@/components/chat/transcript";
import { fetchMessages, type StoredMessage } from "@/lib/api";
import {
  connectVoice,
  openMicrophone,
  type LiveMic,
} from "@/lib/voice";

type VoiceSession = ReturnType<typeof connectVoice>;

type ReceptionChatProps = {
  token: string;
  mode: "new" | "active" | "past";
  conversationId: number | null;
  onBookingsChanged: () => void;
  sidebar?: ReactNode;
};

function ConnectionStatus({ status, micOn }: { status: SessionStatus; micOn: boolean }) {
  const label = statusLabel(status, micOn);
  const state = status === "live"
    ? (micOn ? "listening" : "connected")
    : status === "speaking"
      ? "speaking"
      : status === "connecting" || status === "checking-mic"
        ? "connecting"
        : "idle";
  const title = state === "listening" ? "Line is open"
    : state === "connected" ? "Connected"
      : state === "speaking" ? "Tara is speaking"
        : state === "connecting" ? "Getting things ready"
          : "Session not started";

  return (
    <div className="kk-header-status kk-card-status" aria-live="polite">
      <span className={`kk-status-dot kk-status-${state}`} />
      <span className="kk-status-copy"><strong>{title}</strong><small>{label}</small></span>
    </div>
  );
}

function storedMessages(rows: StoredMessage[]): ChatMessage[] {
  return rows
    .filter((row) => row.role === "user" || row.role === "assistant" || row.role === "choice")
    .map((row) => ({ role: row.role, content: row.content, pending: false }));
}

export function ReceptionChat({
  token,
  mode,
  conversationId,
  onBookingsChanged,
  sidebar,
}: ReceptionChatProps) {
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [status, setStatus] = useState<SessionStatus>("idle");
  const [micOn, setMicOn] = useState(false);
  const [error, setError] = useState("");
  const [ready, setReady] = useState(mode === "new");
  const voiceRef = useRef<VoiceSession | null>(null);
  const micRef = useRef<LiveMic | null>(null);
  const sessionId = useRef(0);
  const liveConversation = useRef<number | null>(conversationId);

  useEffect(() => {
    return () => {
      sessionId.current += 1;
      voiceRef.current?.close();
      micRef.current?.stop();
    };
  }, []);

  useEffect(() => {
    if (mode === "new" || conversationId == null) {
      setReady(true);
      return;
    }
    let cancelled = false;
    setReady(false);
    setError("");
    fetchMessages(token, conversationId)
      .then((result) => {
        if (cancelled) return;
        setMessages(storedMessages(result.messages));
        setReady(true);
      })
      .catch(() => {
        if (cancelled) return;
        setError("That chat could not be loaded.");
        setReady(true);
      });
    return () => {
      cancelled = true;
    };
  }, [conversationId, mode, token]);

  async function handleStart() {
    if (!ready || voiceRef.current || status === "connecting" || status === "checking-mic") {
      return;
    }
    const id = sessionId.current + 1;
    sessionId.current = id;
    setError("");
    setMicOn(false);
    setStatus("checking-mic");

    let mic: LiveMic;
    try {
      mic = await openMicrophone();
    } catch (caught) {
      if (sessionId.current !== id) return;
      setStatus("idle");
      setError(microphoneError(caught));
      return;
    }

    micRef.current = mic;
    if (sessionId.current !== id) {
      mic.stop();
      micRef.current = null;
      return;
    }

    setStatus("connecting");
    voiceRef.current = connectVoice(
      {
        onStatus: (next) => {
          if (sessionId.current !== id) return;
          setStatus(next);
          if (next === "live") {
            setMessages((previous) =>
              previous.map((message) =>
                message.pending && message.role === "assistant"
                  ? { ...message, pending: false }
                  : message,
              ),
            );
          }
          if (next === "idle") {
            voiceRef.current = null;
            onBookingsChanged();
          }
        },
        onTranscript: (role, content) => {
          if (sessionId.current !== id) return;
          setMessages((previous) => appendTranscript(previous, role, content));
        },
        onChoiceList: (content) => {
          if (sessionId.current !== id) return;
          setMessages((previous) => insertChoiceList(previous, content));
        },
        onError: (message) => {
          if (sessionId.current !== id) return;
          setError(message);
        },
        onMic: (enabled) => {
          if (sessionId.current !== id) return;
          setMicOn(enabled);
        },
        onConversation: (nextId) => {
          liveConversation.current = nextId;
        },
      },
      mic,
      token,
      liveConversation.current,
    );
  }

  function handleEnd() {
    sessionId.current += 1;
    voiceRef.current?.close();
    voiceRef.current = null;
    micRef.current?.stop();
    micRef.current = null;
    setMicOn(false);
    setStatus("idle");
    onBookingsChanged();
  }

  async function handleSend() {
    const message = input.trim();
    const sessionOpen = status === "live" || status === "speaking";
    if (!message || !voiceRef.current || !sessionOpen) return;
    setInput("");
    setError("");
    try {
      await voiceRef.current.sendText(message);
    } catch {
      setError("The message did not go through. Start the session again.");
    }
  }

  const readOnly = mode === "past" || (mode !== "new" && conversationId == null);
  const emptyHint = readOnly
    ? "This appointment is finished. The saved chat is shown here."
    : mode === "active"
      ? "This upcoming appointment keeps its chat. Start the session to talk with Tara about it."
      : undefined;

  const startLabel = ready
    ? mode === "active"
      ? "Continue with Tara"
      : "Start talking with Tara"
    : "Loading the chat…";

  return (
    <div className="kk-chat-page kk-chat-shell">
      <ReceptionHeader />
      <div className="kk-chat-workspace">
        {sidebar}
        <main className="kk-chat-main">
          <div className="kk-chat-heading">
            <h1>Tell us what you have <em>in mind.</em></h1>
            <p>Talk naturally with Tara, or type a message below. We’ll help with services and appointments.</p>
          </div>
          <section className="kk-chat-card" aria-label="Conversation with Tara">
            <div className="kk-chat-card-head">
              <div className="kk-tara-avatar">त<span className="kk-avatar-sparkle">✦</span></div>
              <div className="kk-card-head-copy"><strong>Tara</strong><span>Virtual salon receptionist</span></div>
              <ConnectionStatus status={status} micOn={micOn} />
            </div>
            <MessageList messages={messages} emptyHint={emptyHint} />
            {readOnly ? (
              <p className="kk-past-note">
                {error || "Past appointments stay here to read. Start a new chat to book again."}
              </p>
            ) : (
              <ChatComposer
                status={status}
                micOn={micOn}
                input={input}
                error={error}
                startLabel={startLabel}
                canStart={ready}
                onInputChange={setInput}
                onStart={() => {
                  void handleStart();
                }}
                onEnd={handleEnd}
                onSend={() => {
                  void handleSend();
                }}
              />
            )}
          </section>
          <p className="kk-chat-footnote"><span aria-hidden="true">✳</span> You’re in control. Nothing is booked until you confirm the details.</p>
        </main>
      </div>
    </div>
  );
}
