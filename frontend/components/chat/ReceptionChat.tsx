"use client";

import { useEffect, useRef, useState } from "react";
import { ChatComposer } from "@/components/chat/ChatComposer";
import { MessageList } from "@/components/chat/MessageList";
import { ReceptionHeader } from "@/components/chat/ReceptionHeader";
import type { ChatMessage, SessionStatus } from "@/components/chat/types";
import {
  appendTranscript,
  insertChoiceList,
  microphoneError,
} from "@/components/chat/transcript";
import {
  connectVoice,
  openMicrophone,
  type LiveMic,
} from "@/lib/voice";

type VoiceSession = ReturnType<typeof connectVoice>;

export function ReceptionChat() {
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [status, setStatus] = useState<SessionStatus>("idle");
  const [micOn, setMicOn] = useState(false);
  const [error, setError] = useState("");
  const voiceRef = useRef<VoiceSession | null>(null);
  const micRef = useRef<LiveMic | null>(null);
  const sessionId = useRef(0);

  useEffect(() => {
    return () => {
      sessionId.current += 1;
      voiceRef.current?.close();
      micRef.current?.stop();
    };
  }, []);

  async function handleStart() {
    if (voiceRef.current || status === "connecting" || status === "checking-mic") {
      return;
    }
    const id = sessionId.current + 1;
    sessionId.current = id;
    setError("");
    setMessages([]);
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
                  : message
              )
            );
          }
          if (next === "idle") voiceRef.current = null;
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
      },
      mic
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

  return (
    <div className="mx-auto flex h-full w-full max-w-3xl flex-col gap-4 px-4 py-4 sm:px-6 sm:py-5">
      <ReceptionHeader status={status} micOn={micOn} />
      <section className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-3xl border border-[#e7dccf] bg-white/80 shadow-[0_20px_50px_-30px_rgba(70,46,20,0.45)]">
        <MessageList messages={messages} />
        <ChatComposer
          status={status}
          micOn={micOn}
          input={input}
          error={error}
          onInputChange={setInput}
          onStart={() => {
            void handleStart();
          }}
          onEnd={handleEnd}
          onSend={() => {
            void handleSend();
          }}
        />
      </section>
    </div>
  );
}
