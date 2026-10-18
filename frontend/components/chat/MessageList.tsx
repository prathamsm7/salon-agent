"use client";

import { useEffect, useRef } from "react";
import { ChatMessageBubble } from "@/components/chat/ChatMessageBubble";
import type { ChatMessage } from "@/components/chat/types";

const suggestions = ["Explore haircut options", "Find beard styling", "Book an evening slot"];

type MessageListProps = { messages: ChatMessage[]; emptyHint?: string };

export function MessageList({ messages, emptyHint }: MessageListProps) {
  const transcriptRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const node = transcriptRef.current;
    if (!node) return;
    node.scrollTo({ top: node.scrollHeight, behavior: "smooth" });
  }, [messages]);

  return (
    <div ref={transcriptRef} data-transcript className="kk-message-list" aria-live="polite" aria-relevant="additions text">
      {messages.length === 0 ? (
        <div className="kk-empty-state">
          <div className="kk-empty-mark"><span>त</span><i>✦</i></div>
          <span className="kk-empty-eyebrow">NAMASTE, WELCOME TO KESH KALA</span>
          <h2>How can I help you <em>feel your best?</em></h2>
          <p>{emptyHint || "Start a conversation and tell me what you’re looking for. We can explore services, compare options, and plan your visit together."}</p>
          <div className="kk-suggestion-list" aria-label="Things you can ask Tara">
            {suggestions.map((suggestion, index) => <span key={suggestion} className="kk-suggestion"><span>0{index + 1}</span>{suggestion}</span>)}
          </div>
        </div>
      ) : (
        <div className="kk-message-stack">
          {messages.map((message, index) => <ChatMessageBubble key={`${message.role}-${index}`} message={message} />)}
        </div>
      )}
    </div>
  );
}
