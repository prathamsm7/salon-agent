import type { VoiceStatus } from "@/lib/voice";

export type ChatMessage = {
  role: "user" | "assistant" | "choice";
  content: string;
  pending: boolean;
};

export type SessionStatus = VoiceStatus | "checking-mic";
