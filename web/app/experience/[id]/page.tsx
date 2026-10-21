"use client";
import { use, useEffect, useState } from "react";
import Link from "next/link";
import { validExperienceId } from "@/lib/experiences";
import { Sparkline, Starfield, displayNumber } from "@/components/room-ui";
import "@/app/display.css";
import { airMetrics, measurement } from "@/lib/airgradient";
import { availableBedMetrics, bedMetricValue, eightMetrics } from "@/lib/eight-sleep";

type Report = {
  experience: { name: string; started_at: string; ended_at: string | null; band_name: string | null };
  summary: { kind: string; count: string; average: string | null; minimum: number | null; maximum: number | null }[];
  heart: { recorded_at: string; value: number }[];
  room: { kind: string; recorded_at: string; metadata: { measurements?: Record<string, unknown> } }[];
};
export default function ExperienceReport({ params, searchParams }: {
  params: Promise<{ id: string }>; searchParams: Promise<{ before?: string }>;
}) {
  const { id } = use(params);
  const { before } = use(searchParams);
  const recordsHref = "/records" + (before && validExperienceId(before) ? `?before=${before}` : "");
  const [data, setData] = useState<Report | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    fetch(`/api/experiences/${id}/report`, { signal: controller.signal, cache: "no-store" })
      .then(async r => { const body = await r.json(); if (!r.ok) throw new Error(body.error); return body; })
      .then(setData).catch(() => setError("暂时无法读取体验记录")).finally(() => clearTimeout(timeout));
    return () => { controller.abort(); clearTimeout(timeout); };
  }, [id]);
  const heart = data?.summary.find(s => s.kind === "ble_heart_rate");
  return <><Starfield/><main className="report-page"><header><div className="report-navigation"><span>4seas ✦</span><Link className="text-button" href={recordsHref}>← 返回列表</Link></div><h1>{data?.experience.name ?? "体验记录"}</h1>
    {data && <p>{new Date(data.experience.started_at).toLocaleString("zh-CN", { hour12: false })}
      {data.experience.ended_at && ` — ${new Date(data.experience.ended_at).toLocaleTimeString("zh-CN", { hour12: false })}`}</p>}
  </header>{error && <p role="alert">{error}</p>}
  {data && <><section className="report-heart"><h2>心率</h2>
    <div className="report-stats">{[["平均", heart?.average], ["最低", heart?.minimum], ["最高", heart?.maximum]].map(([label, value]) =>
      <article key={label as string}><span>{label}</span><strong>{displayNumber(value == null ? null : Number(value))}</strong><small>bpm</small></article>)}</div>
    <div className="report-chart"><Sparkline points={data.heart.map(s => ({ time: s.recorded_at, value: s.value }))} quiet/></div>
    <p>{data.experience.band_name}</p></section>
    <div className="report-sources">{data.summary.map(s => <article key={s.kind}><h2>{{ ble_heart_rate: "心率记录", airgradient: "环境记录", eight_sleep: "床微环境记录" }[s.kind] ?? "采集记录"}</h2><strong>{Number(s.count).toLocaleString()}</strong><span> 条</span></article>)}</div>
    {data.room.map(source => {
      const payload = source.metadata.measurements;
      const keys = source.kind === "airgradient" ? Object.keys(airMetrics).filter(k => measurement(payload,k) !== null) : availableBedMetrics(payload);
      const definitions = source.kind === "airgradient" ? airMetrics : eightMetrics;
      return <section className="report-room" key={source.kind}><h2>{source.kind === "airgradient" ? "室内环境" : "床微环境"}</h2>
        <div className="report-room-grid">{keys.map(key => <article key={key}><span>{definitions[key].label}</span>
          <strong>{displayNumber(source.kind === "airgradient" ? measurement(payload,key) : bedMetricValue(payload,key))}</strong><small>{definitions[key].unit}</small></article>)}</div>
      </section>;
    })}
  </>}</main></>;
}
