"use client";

import type { SessionStatus } from "@/components/chat/types";

type ChatComposerProps = {
  status: SessionStatus;
  micOn: boolean;
  input: string;
  error: string;
  onInputChange: (value: string) => void;
  onStart: () => void;
  onEnd: () => void;
  onSend: () => void;
};

export function ChatComposer({
  status,
  micOn,
  input,
  error,
  onInputChange,
  onStart,
  onEnd,
  onSend,
}: ChatComposerProps) {
  const sessionOpen = status === "live" || status === "speaking";
  const micPaused = micOn && status === "speaking";

  return (
    <div className="shrink-0 border-t border-[#efe4d6] bg-[#fbf7f2] px-4 py-4 sm:px-6">
      {error && (
        <p
          role="alert"
          className="mb-3 rounded-xl bg-[#fde8e4] px-3 py-2 text-sm text-[#8d2f24]"
        >
          {error}
        </p>
      )}

      {status === "idle" ? (
        <button
          type="button"
          className="w-full rounded-2xl bg-[#2c241c] px-4 py-3 text-sm font-medium text-[#f7f1ea] transition hover:bg-[#3d3228]"
          onClick={onStart}
        >
          Start session
        </button>
      ) : status === "connecting" || status === "checking-mic" ? (
        <div className="space-y-3">
          <button
            type="button"
            className="w-full rounded-2xl bg-[#2c241c]/80 px-4 py-3 text-sm font-medium text-[#f7f1ea]"
            disabled
          >
            {status === "checking-mic"
              ? "Checking the microphone…"
              : "Connecting to Tara…"}
          </button>
          <button
            type="button"
            className="w-full text-sm font-medium text-[#8a6a45]"
            onClick={onEnd}
          >
            Cancel
          </button>
        </div>
      ) : (
        <form
          className="flex flex-col gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            onSend();
          }}
        >
          <div className="flex items-end gap-2">
            <div
              className={`flex h-12 shrink-0 items-center rounded-full px-4 text-sm font-medium text-white ${
                micPaused ? "bg-amber-600" : "bg-red-600"
              }`}
            >
              {micPaused ? "Mic held" : "Mic open"}
            </div>
            <input
              className="min-w-0 flex-1 rounded-2xl border border-[#e4d8c8] bg-white px-4 py-3 text-[15px] outline-none placeholder:text-[#a89886] focus:border-[#c4a574]"
              value={input}
              onChange={(event) => onInputChange(event.target.value)}
              placeholder="Ask for a haircut, a time, or a booking…"
              disabled={!sessionOpen}
            />
            <button
              className="rounded-2xl bg-[#2c241c] px-4 py-3 text-sm font-medium text-[#f7f1ea] disabled:opacity-40"
              disabled={!sessionOpen || !input.trim()}
            >
              Send
            </button>
          </div>
          <div className="flex items-center justify-between gap-3 text-xs text-[#6d6258]">
            <p>
              {micPaused
                ? "The microphone stays open, but audio is held while Tara speaks."
                : "Microphone stays open for this session. Speak naturally."}
            </p>
            <button
              type="button"
              className="shrink-0 font-medium text-[#8a6a45] underline-offset-2 hover:underline"
              onClick={onEnd}
            >
              End session
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
