"use client";

import { useEffect, useState } from "react";
import type { Experience, ExperienceRecords, Source } from "@/lib/types";
import { ExperienceBar } from "./experience-bar";
import { ExperienceReceipt } from "./experience-receipt";
import "@/app/display.css";
import { displayNumber, Icon } from "./room-ui";

function dateTime(value: string) {
  return new Date(value).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour12: false,
    hour: "2-digit", minute: "2-digit", second: "2-digit" });
}
function elapsed(start: string, now: number) {
  const seconds = Math.max(0, Math.floor((now - Date.parse(start)) / 1000));
  return [Math.floor(seconds / 3600), Math.floor(seconds / 60) % 60, seconds % 60]
    .map(n => String(n).padStart(2, "0")).join(":");
}
async function requestJson(url: string, init?: RequestInit) {
  const response = await fetch(url, { cache: "no-store", ...init });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "操作失败，请重试。");
  return result;
}

function ExperienceViewer({ id, onClose }: { id: string; onClose: () => void }) {
  const [source, setSource] = useState("");
  const [before, setBefore] = useState<string | null>(null);
  const [data, setData] = useState<ExperienceRecords | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let disposed = false;
    let controller: AbortController;
    let timer: ReturnType<typeof setTimeout>;
    setData(null); setLoading(true); setError("");
    async function refresh() {
      controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 10000);
      try {
        const query = new URLSearchParams();
        if (source) query.set("source", source);
        if (before) query.set("before", before);
        const result: ExperienceRecords = await requestJson(`/api/experiences/${id}?${query}`, { signal: controller.signal });
        if (!disposed) { setData(result); setError(""); }
      } catch (e) {
        if (!disposed) setError(e instanceof Error && e.name !== "AbortError" ? e.message : "读取超时，正在重试。");
      } finally {
        clearTimeout(timeout);
        if (!disposed) { setLoading(false); timer = setTimeout(refresh, 3000); }
      }
    }
    void refresh();
    return () => { disposed = true; controller?.abort(); clearTimeout(timer); };
  }, [id, source, before]);

  return <section className="experience-viewer" aria-label="体验数据">
    <div className="detail-section-title"><div><h3>{data?.experience.name ?? "体验数据"}</h3>
      {data && <p>{dateTime(data.experience.started_at)} — {data.experience.ended_at ? dateTime(data.experience.ended_at) : "进行中"}</p>}</div>
      <button className="text-button" onClick={onClose}>关闭记录</button></div>
    {error && <p role="alert" className="notice">{error}</p>}
    <div className="metric-select"><label htmlFor="experience-source">数据源</label>
      <select id="experience-source" value={source} onChange={e => { setSource(e.target.value); setBefore(null); }}>
        <option value="">全部数据源</option>{data?.sources.map(s => <option key={s.id} value={s.id}>{s.name} · {s.sample_count} 条</option>)}
      </select><span>按入库顺序 · 每页 50 条</span></div>
    <div className="table-wrap"><table><thead><tr><th>采样时间</th><th>数据源</th><th>读数与指标</th></tr></thead><tbody>
      {data?.samples.map(sample => <tr key={sample.id}><td>{dateTime(sample.recorded_at)}</td><td>{sample.source_name}</td><td>
        <span>{displayNumber(sample.value)} <span className="muted">{sample.unit}</span></span>
        <details className="sample-fields"><summary>查看指标与状态</summary><pre>{JSON.stringify(sample.metadata, null, 2)}</pre></details>
      </td></tr>)}
      {!data?.samples.length && <tr><td colSpan={3} className="empty-note">{loading ? "正在读取体验数据…" : error ? "暂时无法读取" : "这段时间还没有采集数据。请确认数据源已启用且设备在线。"}</td></tr>}
    </tbody></table></div>
    <div className="experience-pagination"><button className="text-button" onClick={() => setBefore(null)} disabled={!before || loading}>返回最新记录</button>
      <button className="button" onClick={() => setBefore(data?.next ?? null)} disabled={!data?.next || loading}>更早的记录</button></div>
    <p className="detail-note">只展示归属于本次体验的样本。Eight Sleep 按云端快照接收时间归档，快照中的睡眠记录可能来自更早日期；全部接口原文保存在数据库中。</p>
  </section>;
}

export function ExperiencePanel({ active, sources, clientId, onSelect, now, ready, onChanged }: {
  active: Experience | null | undefined; sources: Source[]; clientId: string | null;
  onSelect: (id: string) => void; now: number; ready: boolean; onChanged: () => void;
}) {
  const [receipt, setReceipt] = useState<Experience | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [history, setHistory] = useState<Experience[]>([]);
  const [historyError, setHistoryError] = useState("");
  const [historyLoading, setHistoryLoading] = useState(false);
  const [next, setNext] = useState<string | null>(null);
  const [before, setBefore] = useState<string | null>(null);
  const [viewing, setViewing] = useState<string | null>(null);


  useEffect(() => {
    if (!historyOpen) return;
    let disposed = false;
    let controller: AbortController;
    let timer: ReturnType<typeof setTimeout>;
    setHistory([]); setHistoryLoading(true); setHistoryError("");
    async function refresh() {
      controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 10000);
      try {
        const result = await requestJson("/api/experiences" + (before ? `?before=${encodeURIComponent(before)}` : ""), { signal: controller.signal });
        if (!disposed) { setHistory(result.experiences); setNext(result.next); setHistoryError(""); }
      } catch (e) {
        if (!disposed) setHistoryError(e instanceof Error && e.name !== "AbortError" ? e.message : "读取体验列表超时，正在重试。");
      } finally {
        clearTimeout(timeout);
        if (!disposed) { setHistoryLoading(false); timer = setTimeout(refresh, 3000); }
      }
    }
    void refresh();
    return () => { disposed = true; controller?.abort(); clearTimeout(timer); };
  }, [historyOpen, before, active?.id]);

  return <section className="experience-module" aria-label="体验管理">
    <ExperienceBar active={active} sources={sources} clientId={clientId} onSelect={onSelect}
      now={now} ready={ready} onChanged={onChanged}/>
    <div className="experience-bottom"><span>本机负责当前体验者，心率按所选手环记录</span>
      <button className="text-button" aria-expanded={historyOpen} onClick={() => setHistoryOpen(v => !v)}>{historyOpen ? "收起体验记录" : "查看体验记录"}<Icon name="arrow"/></button></div>
    {receipt && <ExperienceReceipt experience={receipt} onClose={() => setReceipt(null)}/>}
    {viewing && history.find(e => e.id === viewing)?.ended_at && <button className="button" onClick={() => setReceipt(history.find(e => e.id === viewing)!)}>记录二维码</button>}
    {historyOpen && <div className="experience-history">
      {historyError && <p role="alert" className="notice">{historyError}</p>}
      <div className="experience-list">{history.map(item => <button className={`experience-item ${viewing === item.id ? "is-selected" : ""}`} key={item.id} onClick={() => setViewing(item.id)}>
        <strong>{item.name}</strong><span>{dateTime(item.started_at)}</span><span>{item.ended_at ? "已结束" : "体验中"} · {Number(item.sample_count).toLocaleString()} 条</span><Icon name="arrow"/>
      </button>)}</div>
      {!history.length && <p className="empty-note">{historyLoading ? "正在读取体验记录…" : historyError ? "体验记录暂时不可用" : "还没有体验记录，输入名字即可开始。"}</p>}
      {(before || next) && <div className="experience-pagination"><button className="text-button" disabled={!before || historyLoading} onClick={() => setBefore(null)}>最新体验</button><button className="button" disabled={!next || historyLoading} onClick={() => setBefore(next)}>更早的体验</button></div>}
      {viewing && <ExperienceViewer key={viewing} id={viewing} onClose={() => setViewing(null)}/>}
    </div>}
  </section>;
}
