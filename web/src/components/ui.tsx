"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import type { Risk } from "@/lib/types";
import { RISK_COLORS } from "@/lib/types";

export function Card({ title, children, highlight, right }: { title: string; children: ReactNode; highlight?: boolean; right?: ReactNode }) {
  return (
    <section
      className={`rounded-xl border bg-white p-3 shadow-sm ${highlight ? "border-blue-500 ring-2 ring-blue-200" : "border-zinc-200"}`}
    >
      <div className="mb-2 flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-zinc-800">{title}</h2>
        {right}
      </div>
      {children}
    </section>
  );
}

export function Badge({ children, tone = "zinc" }: { children: ReactNode; tone?: "zinc" | "amber" | "red" | "green" | "blue" }) {
  const tones = {
    zinc: "bg-zinc-100 text-zinc-700",
    amber: "bg-amber-100 text-amber-800",
    red: "bg-red-100 text-red-700",
    green: "bg-green-100 text-green-800",
    blue: "bg-blue-100 text-blue-800",
  } as const;
  return <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold ${tones[tone]}`}>{children}</span>;
}

export function RiskBadge({ risk }: { risk: Risk }) {
  return (
    <span
      className="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-bold uppercase text-white"
      style={{ background: RISK_COLORS[risk], color: risk === "low" ? "#422006" : "#fff" }}
    >
      {risk} risk
    </span>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded bg-zinc-200 ${className}`} />;
}

/** Number that eases from its previous value to the new one. */
export function AnimatedNumber({ value, duration = 600 }: { value: number; duration?: number }) {
  const [shown, setShown] = useState(value);
  const shownRef = useRef(value);
  useEffect(() => {
    const from = shownRef.current;
    if (from === value) return;
    const start = performance.now();
    let raf = 0;
    const tick = (t: number) => {
      const k = Math.min(1, (t - start) / duration);
      const eased = 1 - Math.pow(1 - k, 3);
      const next = Math.round(from + (value - from) * eased);
      shownRef.current = next;
      setShown(next);
      if (k < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [value, duration]);
  return <>{shown.toLocaleString("en-US")}</>;
}

export function Modal({ open, onClose, title, children }: { open: boolean; onClose: () => void; title: string; children: ReactNode }) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="max-h-[85vh] w-full max-w-lg overflow-y-auto rounded-2xl bg-white p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-start justify-between gap-4">
          <h2 className="text-lg font-bold text-zinc-900">{title}</h2>
          <button onClick={onClose} className="rounded-lg px-2 py-1 text-zinc-500 hover:bg-zinc-100" aria-label="Close">
            ✕
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
