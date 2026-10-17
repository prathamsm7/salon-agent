import type { ChatMessage } from "@/components/chat/types";

export function joinTranscript(current: string, next: string) {
  if (!current) return next;
  if (!next) return current;
  if (/\s$/.test(current) || /^\s/.test(next)) return current + next;
  return `${current} ${next}`;
}

export function spokenText(content: string) {
  return content
    .replace(/\*\*|__|`/g, "")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

export function closePending(previous: ChatMessage[]) {
  return previous.map((message) =>
    message.pending ? { ...message, pending: false } : message
  );
}

export function appendTranscript(
  previous: ChatMessage[],
  role: "user" | "assistant",
  content: string,
): ChatMessage[] {
  const pendingIndex = previous.findLastIndex(
    (message) => message.pending && message.role === role
  );
  if (pendingIndex !== -1) {
    const next = previous.slice();
    next[pendingIndex] = {
      ...next[pendingIndex],
      content: joinTranscript(next[pendingIndex].content, content),
    };
    return next;
  }

  return [...closePending(previous), { role, content, pending: true }];
}

export function insertChoiceList(
  previous: ChatMessage[],
  content: string,
): ChatMessage[] {
  const withoutOldChoice = previous.filter((message) => message.role !== "choice");
  const assistantIndex = withoutOldChoice.findLastIndex(
    (message) => message.role === "assistant"
  );
  const choiceMessage: ChatMessage = {
    role: "choice",
    content,
    pending: false,
  };
  if (assistantIndex === -1) {
    return [...withoutOldChoice, choiceMessage];
  }
  return [
    ...withoutOldChoice.slice(0, assistantIndex + 1),
    choiceMessage,
    ...withoutOldChoice.slice(assistantIndex + 1),
  ];
}

export function microphoneError(caught: unknown) {
  if (caught instanceof DOMException && caught.name === "NotAllowedError") {
    return "Microphone access was blocked. Allow it for this site, then start again.";
  }
  if (caught instanceof DOMException && caught.name === "NotFoundError") {
    return "No microphone was found. Connect one, then start again.";
  }
  return "Could not use the microphone, so the session was not started.";
}

export function statusLabel(
  status: import("@/components/chat/types").SessionStatus,
  micOn: boolean,
) {
  if (status === "checking-mic") return "Checking your microphone";
  if (status === "connecting") return "Microphone ready. Opening the line";
  if (status === "speaking") {
    return micOn ? "Tara is speaking. Microphone paused." : "Tara is speaking";
  }
  if (status === "live") {
    return micOn ? "Listening" : "Connected. Speak or type.";
  }
  return "Session not started";
}
