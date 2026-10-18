"use client";

import type { SessionStatus } from "@/components/chat/types";

type ChatComposerProps = {
  status: SessionStatus;
  micOn: boolean;
  input: string;
  error: string;
  startLabel?: string;
  canStart?: boolean;
  onInputChange: (value: string) => void;
  onStart: () => void;
  onEnd: () => void;
  onSend: () => void;
};

function MicIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="3" width="6" height="12" rx="3" fill="none" stroke="currentColor" strokeWidth="1.6"/><path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v3m-4 0h8" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/></svg>;
}
function SendIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m21 3-7.3 18-3.8-7.9L2 9.3 21 3Z" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round"/><path d="M21 3 9.9 13.1" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/></svg>;
}
function StopIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor"/></svg>;
}

export function ChatComposer({ status, micOn, input, error, startLabel = "Start talking with Tara", canStart = true, onInputChange, onStart, onEnd, onSend }: ChatComposerProps) {
  const sessionOpen = status === "live" || status === "speaking";
  const busy = status === "connecting" || status === "checking-mic";

  return (
    <div className="kk-chat-composer">
      {error && <p role="alert" className="kk-error-message"><span aria-hidden="true">!</span>{error}</p>}

      {status === "idle" ? (
        <div className="kk-start-session">
          <button type="button" className="kk-start-voice" onClick={onStart} disabled={!canStart}>
            <span className="kk-start-mic"><MicIcon /></span>
            <span className="kk-start-copy"><strong>{startLabel}</strong><small>We’ll check your microphone before connecting</small></span>
            <span className="kk-start-arrow" aria-hidden="true">↗</span>
          </button>
          <p className="kk-composer-hint">Prefer typing? Start the session first, then send a message here.</p>
        </div>
      ) : busy ? (
        <div className="kk-connecting-panel">
          <span className="kk-loading-ring" />
          <span><strong>{status === "checking-mic" ? "Checking your microphone" : "Connecting to Tara"}</strong><small>{status === "checking-mic" ? "Allow microphone access when prompted." : "Getting your conversation ready…"}</small></span>
          <button type="button" className="kk-text-button" onClick={onEnd}>Cancel</button>
        </div>
      ) : (
        <form className="kk-live-composer" onSubmit={(event) => { event.preventDefault(); onSend(); }}>
          <div className="kk-live-status-row">
            <span className={`kk-listening-pill ${status === "speaking" ? "is-speaking" : ""}`}>
              <span className="kk-live-dot" />{status === "speaking" ? "Tara is speaking" : micOn ? "Listening to you" : "Voice connected"}
            </span>
            <button type="button" className="kk-end-button" onClick={onEnd}><StopIcon /> End session</button>
          </div>
          <div className="kk-compose-row">
            <span className={`kk-mic-indicator ${micOn ? "is-on" : ""}`} title={micOn ? "Microphone active" : "Microphone paused"}><MicIcon /></span>
            <input
              value={input}
              onChange={(event) => onInputChange(event.target.value)}
              placeholder="Type a message to Tara…"
              aria-label="Message to Tara"
              disabled={!sessionOpen}
            />
            <button type="submit" className="kk-send-button" disabled={!sessionOpen || !input.trim()} aria-label="Send message"><SendIcon /></button>
          </div>
          <p className="kk-composer-hint">Speak naturally, or type a message. Your appointment is not booked until you confirm.</p>
        </form>
      )}
    </div>
  );
}
