"use client";

import { useEffect, useRef } from "react";
import { ChatMessageBubble } from "@/components/chat/ChatMessageBubble";
import type { ChatMessage } from "@/components/chat/types";

type MessageListProps = {
  messages: ChatMessage[];
};

export function MessageList({ messages }: MessageListProps) {
  const transcriptRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const node = transcriptRef.current;
    if (!node) return;
    node.scrollTo({
      top: node.scrollHeight,
      behavior: "smooth",
    });
  }, [messages]);

  return (
    <div
      ref={transcriptRef}
      className="min-h-0 flex-1 space-y-4 overflow-y-auto overscroll-contain px-4 py-5 sm:px-6"
    >
      {messages.length === 0 ? (
        <div className="flex h-full min-h-48 flex-col items-center justify-center text-center">
          <p className="text-lg font-medium">Ready when you are</p>
          <p className="mt-2 max-w-sm text-sm leading-6 text-[#6d6258]">
            Start a session. We check the microphone first, then leave it open so
            you can talk with Tara. You can still type.
          </p>
        </div>
      ) : (
        messages.map((message, index) => (
          <ChatMessageBubble
            key={`${message.role}-${index}`}
            message={message}
          />
        ))
      )}
    </div>
  );
}
