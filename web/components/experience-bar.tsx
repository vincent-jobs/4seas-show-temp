"use client";

import { useState } from "react";
import type { Experience, Source } from "@/lib/types";
import { availableHeartBand } from "@/lib/heart-rate";
import { experienceName } from "@/lib/experiences";
import { ExperienceReceipt } from "./experience-receipt";

export function ExperienceBar({ active, sources, clientId, now, ready, onChanged, onSelect }: {
  active: Experience | null | undefined; sources: Source[]; clientId: string | null;
  now: number; ready: boolean; onChanged: () => void; onSelect: (id: string) => void;
}) {
  const [name, setName] = useState("");
  const [band, setBand] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [receipt, setReceipt] = useState<Experience | null>(null);
  const available = sources.filter(s => availableHeartBand(s, now));
  const selectedBand = available.some(s => s.id === band) ? band : "";
  const seconds = active ? Math.max(0, Math.floor((now - Date.parse(active.started_at)) / 1000)) : 0;
  const duration = [Math.floor(seconds / 3600), Math.floor(seconds / 60) % 60, seconds % 60]
    .map(n => String(n).padStart(2, "0")).join(":");

  async function submit() {
    if (busy || !ready || !clientId || (!active && (!experienceName(name) || !selectedBand))) return;
    setBusy(true); setError("");
    try {
      const response = await fetch(active ? `/api/experiences/${active.id}` : "/api/experiences", {
        method: active ? "PATCH" : "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ client_id: clientId, name: experienceName(name), heart_source_id: selectedBand }),
        signal: AbortSignal.timeout(10000),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "请重试");
      if (active) setReceipt(result);
      else { onSelect(result.heart_source_id); setName(""); }
    } catch (e) { setError(e instanceof Error ? e.message : "请重试"); }
    finally { setBusy(false); onChanged(); }
  }

  return <>
    <section className="display-experience" aria-label="体验">
      <span className="display-experience-label">体验</span>
      {active ? <>
        <strong className="display-participant" title={active.name}>{active.name}</strong>
        <span className="display-band-name">{sources.find(s => s.id === active.heart_source_id)?.name}</span>
        <time className="display-duration" aria-label="体验时长">{duration}</time>
        <button className="display-action" onClick={submit} disabled={busy || !ready}>{busy ? "…" : "结束体验"}</button>
      </> : <form onSubmit={e => { e.preventDefault(); void submit(); }}>
        <label className="sr-only" htmlFor="display-participant">体验者姓名</label>
        <input id="display-participant" value={name} onChange={e => { setName(e.target.value); setError(""); }}
          placeholder="体验者姓名" maxLength={60} autoComplete="off" required disabled={busy || !ready}/>
        <label className="sr-only" htmlFor="experience-band">选择手环</label>
        <select id="experience-band" value={selectedBand} onChange={e => { setBand(e.target.value); onSelect(e.target.value); setError(""); }}
          disabled={busy || !ready} required>
          <option value="">选择手环</option>
          {available.map(s => <option key={s.id} value={s.id}>{s.name} · {s.id.slice(-4).toUpperCase()}</option>)}
        </select>
        <button className="display-action" type="submit" disabled={busy || !ready || !clientId || !experienceName(name) || !selectedBand}>
          {busy ? "…" : "开始体验"}
        </button>
      </form>}
    </section>
    {error && <div className="experience-error" role="alert" onClick={() => setError("")}>{error}</div>}
    {receipt && <ExperienceReceipt experience={receipt} onClose={() => setReceipt(null)}/>}
  </>;
}
