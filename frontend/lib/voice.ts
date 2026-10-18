export type VoiceStatus = "idle" | "connecting" | "live" | "speaking";

export type VoiceHandlers = {
  onStatus: (state: VoiceStatus) => void;
  onTranscript: (role: "user" | "assistant", content: string) => void;
  onChoiceList?: (content: string) => void;
  onError: (message: string) => void;
  onMic: (enabled: boolean) => void;
  onConversation?: (id: number) => void;
};

const TARGET_RATE = 24000;

const WORKLET_SOURCE = `
class PcmProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buffer = new Float32Array(4096);
    this.offset = 0;
  }

  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (!channel) return true;
    let remaining = channel;
    while (remaining.length) {
      const space = this.buffer.length - this.offset;
      const take = Math.min(space, remaining.length);
      this.buffer.set(remaining.subarray(0, take), this.offset);
      this.offset += take;
      remaining = remaining.subarray(take);
      if (this.offset === this.buffer.length) {
        this.port.postMessage(this.buffer.slice(0));
        this.offset = 0;
      }
    }
    return true;
  }
}
registerProcessor("pcm-processor", PcmProcessor);
`;

function voiceSocketUrl(token: string, conversationId?: number | null): string {
  const httpUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
  const wsUrl = httpUrl.replace(/^http/, "ws");
  const params = new URLSearchParams({ token });
  if (conversationId) params.set("conversation_id", String(conversationId));
  return `${wsUrl}/api/voice?${params}`;
}

function downsampleToPcm16(input: Float32Array, inputRate: number): ArrayBuffer {
  if (inputRate === TARGET_RATE) {
    return floatToPcm16(input);
  }
  const ratio = inputRate / TARGET_RATE;
  const length = Math.max(1, Math.floor(input.length / ratio));
  const downsampled = new Float32Array(length);
  for (let index = 0; index < length; index += 1) {
    const start = Math.floor(index * ratio);
    const end = Math.min(input.length, Math.floor((index + 1) * ratio));
    let sum = 0;
    let count = 0;
    for (let sample = start; sample < end; sample += 1) {
      sum += input[sample];
      count += 1;
    }
    downsampled[index] = count ? sum / count : 0;
  }
  return floatToPcm16(downsampled);
}

function floatToPcm16(input: Float32Array): ArrayBuffer {
  const pcm = new Int16Array(input.length);
  for (let index = 0; index < input.length; index += 1) {
    const clamped = Math.max(-1, Math.min(1, input[index]));
    pcm[index] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff;
  }
  return pcm.buffer;
}

export type LiveMic = {
  setSender: (send: ((pcm: ArrayBuffer) => void) | null) => void;
  stop: () => void;
};

export async function openMicrophone(): Promise<LiveMic> {
  const capture = new AudioContext();
  let sender: ((pcm: ArrayBuffer) => void) | null = null;
  let stopped = false;
  let stream: MediaStream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        channelCount: 1,
      },
    });
  } catch (error) {
    void capture.close();
    throw error;
  }
  const workletUrl = URL.createObjectURL(
    new Blob([WORKLET_SOURCE], { type: "application/javascript" })
  );
  try {
    await capture.audioWorklet.addModule(workletUrl);
  } catch (error) {
    stream.getTracks().forEach((track) => track.stop());
    void capture.close();
    throw error;
  } finally {
    URL.revokeObjectURL(workletUrl);
  }
  const source = capture.createMediaStreamSource(stream);
  const processor = new AudioWorkletNode(capture, "pcm-processor");
  const mute = capture.createGain();
  mute.gain.value = 0;
  processor.port.onmessage = (event: MessageEvent<Float32Array>) => {
    if (!sender || stopped) return;
    const pcm = downsampleToPcm16(event.data, capture.sampleRate);
    if (pcm.byteLength) sender(pcm);
  };
  source.connect(processor);
  processor.connect(mute);
  mute.connect(capture.destination);

  return {
    setSender(send) {
      sender = send;
    },
    stop() {
      if (stopped) return;
      stopped = true;
      sender = null;
      processor.port.onmessage = null;
      processor.disconnect();
      source.disconnect();
      mute.disconnect();
      stream.getTracks().forEach((track) => track.stop());
      void capture.close();
    },
  };
}

export function connectVoice(
  handlers: VoiceHandlers,
  mic: LiveMic,
  token: string,
  conversationId?: number | null,
) {
  const socket = new WebSocket(voiceSocketUrl(token, conversationId));
  socket.binaryType = "arraybuffer";

  let playback = new AudioContext();
  let nextPlayTime = 0;
  let unlocked = false;
  let agentSpeaking = false;
  let closing = false;
  let becameLive = false;
  let reportedError = false;
  handlers.onMic(true);
  mic.setSender((pcm) => {
    if (closing || agentSpeaking || socket.readyState !== WebSocket.OPEN) return;
    socket.send(pcm);
  });
  const pendingAudio: ArrayBuffer[] = [];
  let drainTimer = 0;

  void playback.resume().then(() => {
    unlocked = true;
    const queued = pendingAudio.splice(0);
    for (const chunk of queued) playPcm(chunk);
  });

  function markAudible() {
    window.clearTimeout(drainTimer);
    if (!agentSpeaking) {
      agentSpeaking = true;
      handlers.onStatus("speaking");
    }
  }

  function markQuiet() {
    window.clearTimeout(drainTimer);
    const delay = Math.max(0, (nextPlayTime - playback.currentTime) * 1000);
    drainTimer = window.setTimeout(() => {
      agentSpeaking = false;
      if (!closing && becameLive) handlers.onStatus("live");
    }, delay + 80);
  }

  function playPcm(bytes: ArrayBuffer) {
    if (playback.state === "closed") return;
    const samples = new Int16Array(bytes);
    if (!samples.length) return;
    const floats = new Float32Array(samples.length);
    for (let index = 0; index < samples.length; index += 1) {
      floats[index] = samples[index] / 32768;
    }
    const buffer = playback.createBuffer(1, floats.length, TARGET_RATE);
    buffer.copyToChannel(floats, 0);
    const source = playback.createBufferSource();
    source.buffer = buffer;
    source.connect(playback.destination);
    const startAt = Math.max(playback.currentTime, nextPlayTime);
    source.start(startAt);
    nextPlayTime = startAt + buffer.duration;
    markAudible();
  }

  function releaseMic() {
    mic.setSender(null);
    mic.stop();
    handlers.onMic(false);
  }

  function endSession() {
    if (closing) return;
    closing = true;
    releaseMic();
    window.clearTimeout(drainTimer);
    if (socket.readyState === WebSocket.OPEN) {
      socket.close();
    } else if (socket.readyState === WebSocket.CONNECTING) {
      socket.addEventListener("open", () => socket.close(), { once: true });
    } else {
      handlers.onStatus("idle");
    }
    void playback.close();
  }

  socket.onmessage = (event) => {
    if (closing) return;
    if (typeof event.data !== "string") {
      const bytes = event.data as ArrayBuffer;
      if (!unlocked) {
        pendingAudio.push(bytes);
        return;
      }
      playPcm(bytes);
      return;
    }

    const message = JSON.parse(event.data) as {
      type?: string;
      state?: VoiceStatus | "closed";
      role?: "user" | "assistant";
      content?: string;
      value?: boolean;
      message?: string;
      id?: number;
    };

    if (message.type === "conversation" && typeof message.id === "number") {
      handlers.onConversation?.(message.id);
      return;
    }

    if (message.type === "status" && message.state === "closed") {
      handlers.onError("The voice line closed.");
      endSession();
      return;
    }
    if (message.type === "status" && message.state === "live") {
      becameLive = true;
      handlers.onStatus("live");
      return;
    }
    if (message.type === "status" && message.state === "connecting") {
      handlers.onStatus("connecting");
      return;
    }
    if (message.type === "speaking") {
      if (message.value) markAudible();
      else markQuiet();
      return;
    }
    if (message.type === "transcript" && message.role && message.content) {
      handlers.onTranscript(message.role, message.content);
      return;
    }
    if (message.type === "choice_list" && message.content) {
      handlers.onChoiceList?.(message.content);
      return;
    }
    if (message.type === "error" && message.message) {
      reportedError = true;
      handlers.onError(message.message);
    }
  };

  socket.onerror = () => {
    if (closing) return;
    handlers.onError(
      "Could not open the voice session. Check that the API is running on port 8000."
    );
  };

  socket.onclose = () => {
    releaseMic();
    window.clearTimeout(drainTimer);
    if (closing) {
      handlers.onStatus("idle");
      return;
    }
    handlers.onStatus("idle");
    if (!becameLive && !reportedError) {
      handlers.onError("The voice session closed before Tara was ready.");
    }
  };

  return {
    async sendText(content: string) {
      if (playback.state === "suspended") await playback.resume();
      if (socket.readyState !== WebSocket.OPEN) {
        throw new Error("Voice connection is not open.");
      }
      socket.send(JSON.stringify({ type: "text", content }));
    },
    close() {
      endSession();
    },
  };
}
