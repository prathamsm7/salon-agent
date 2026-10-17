import type { ChatMessage } from "@/components/chat/types";
import { spokenText } from "@/components/chat/transcript";

type ChatMessageBubbleProps = {
  message: ChatMessage;
};

export function ChatMessageBubble({ message }: ChatMessageBubbleProps) {
  const label =
    message.role === "user" ? "You" : message.role === "choice" ? "Options" : "Tara";
  const bubbleClass =
    message.role === "user"
      ? "bg-[#2c241c] text-[#f7f1ea]"
      : message.role === "choice"
        ? "border border-[#e4d8c8] bg-white text-[#2c241c]"
        : "border border-[#efe4d6] bg-[#fbf7f2] text-[#2c241c]";

  return (
    <div
      className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}
    >
      <div className={`max-w-[90%] rounded-2xl px-4 py-3 ${bubbleClass}`}>
        <p className="mb-1 text-[11px] font-medium tracking-wide uppercase opacity-70">
          {label}
        </p>
        <p className="whitespace-pre-wrap text-[15px] leading-6">
          {spokenText(message.content)}
        </p>
      </div>
    </div>
  );
}
