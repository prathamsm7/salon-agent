import type { ChatMessage } from "@/components/chat/types";
import { spokenText } from "@/components/chat/transcript";

type ChatMessageBubbleProps = { message: ChatMessage };

export function ChatMessageBubble({ message }: ChatMessageBubbleProps) {
  const label = message.role === "user" ? "You" : message.role === "choice" ? "Service options" : "Tara · Kesh Kala";
  const isUser = message.role === "user";

  return (
    <div className={`kk-message-row ${isUser ? "is-user" : "is-assistant"}`}>
      {!isUser && <span className={`kk-message-avatar ${message.role === "choice" ? "is-choice" : ""}`} aria-hidden="true">{message.role === "choice" ? "✦" : "त"}</span>}
      <div className={`kk-message-bubble ${isUser ? "kk-user-bubble" : message.role === "choice" ? "kk-choice-bubble" : "kk-assistant-bubble"}`}>
        <p className="kk-message-label">{label}</p>
        <p className="kk-message-content">{spokenText(message.content)}</p>
        {message.pending && message.role === "assistant" && <span className="kk-message-pending"><i /> composing</span>}
      </div>
    </div>
  );
}
