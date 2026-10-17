import type { SessionStatus } from "@/components/chat/types";
import { statusLabel } from "@/components/chat/transcript";

type ReceptionHeaderProps = {
  status: SessionStatus;
  micOn: boolean;
};

export function ReceptionHeader({ status, micOn }: ReceptionHeaderProps) {
  const label = statusLabel(status, micOn);
  const dotClass =
    status === "live"
      ? micOn
        ? "bg-emerald-500"
        : "bg-[#c4a574]"
      : status === "speaking"
        ? "animate-pulse bg-[#c4a574]"
        : status === "connecting" || status === "checking-mic"
          ? "animate-pulse bg-amber-500"
          : "bg-[#c8beb2]";

  return (
    <header className="flex shrink-0 items-start justify-between gap-4">
      <div>
        <p className="text-xs font-medium tracking-[0.22em] text-[#8a6a45] uppercase">
          Kesh Kala
        </p>
        <h1 className="mt-1 text-3xl font-semibold tracking-tight">Reception</h1>
        <p className="mt-1 text-sm text-[#6d6258]">Tara, your salon receptionist</p>
      </div>
      <div className="flex items-center gap-2 rounded-full border border-[#e4d8c8] bg-white/80 px-3 py-1.5 text-sm shadow-sm">
        <span className={`h-2.5 w-2.5 rounded-full ${dotClass}`} />
        <span>{label}</span>
      </div>
    </header>
  );
}
