"use client";

import { useState } from "react";
import { airMetrics, measurement } from "@/lib/airgradient";
import { eightMetrics, lastBedDisplay } from "@/lib/eight-sleep";
import { freshFor, isSourceFresh, sourceStatus } from "@/lib/dashboard";
import { heartRateStatus, heartRateValue } from "@/lib/heart-rate";
import { frequency } from "@/lib/stats";
import type { Dashboard } from "@/lib/types";
import { displayNumber, displayTime, Icon, Sparkline } from "./room-ui";

export function SourceExplorer({ data, selected, now, collectorOnline, onSelect, onChanged }: {
  data: Dashboard | null; selected: string | null; now: number; collectorOnline: boolean;
  onSelect: (id: string) => void; onChanged: () => void;
}) {
  const [airMetric, setAirMetric] = useState("rco2");
  const [eightMetric, setEightMetric] = useState("currentDeviceLevel");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const source = data?.sources.find(s => s.id === data.selectedSourceId);
  const switching = !!selected && selected !== data?.selectedSourceId;
  const isAir = source?.kind === "airgradient", isEight = source?.kind === "eight_sleep";
  const isHeart = source?.metric === "heart_rate", multi = isAir || isEight;
  const definitions = isEight ? eightMetrics : airMetrics;
  const key = isEight ? eightMetric : airMetric;
  const payload = source?.latest_metadata?.measurements;
  const available = [...new Set([...Object.keys(definitions), ...Object.keys(payload ?? {}).filter(k => measurement(payload, k) !== null)])];
  const snapshots = data?.samples ?? [];
  const samples = snapshots.map(s => ({ ...s, value: multi ? measurement(s.metadata.measurements, key) : isHeart ? heartRateValue(s.value, s.metadata) : s.value }));
  const retainedBed = isEight ? lastBedDisplay(source, snapshots) : undefined;
  const valueTime = retainedBed?.updated_at[key] ?? source?.last_sample_at;
  const value = multi ? measurement(retainedBed?.measurements ?? payload, key) : isHeart ? heartRateValue(source?.latest_value, source?.latest_metadata) : source?.latest_value;
  const label = multi ? definitions[key]?.label ?? key : isHeart ? "心率" : source?.metric ?? "读数";
  const unit = multi ? definitions[key]?.unit ?? "" : source?.unit ?? "";
  const live = isSourceFresh(source, collectorOnline, now);
  const hz = live ? frequency(snapshots, now, freshFor(source)) : null;

  async function toggle() {
    if (!source || switching || busy) return;
    setBusy(true); setError("");
    try {
      const response = await fetch(`/api/sources/${encodeURIComponent(source.id)}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: !source.enabled }), signal: AbortSignal.timeout(10000),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "保存失败");
      onChanged();
    } catch (e) { setError(e instanceof Error ? e.message : "保存失败"); }
    finally { setBusy(false); }
  }

  return <div className="explorer-content">
    <div className="source-tabs" aria-label="选择数据源">{data?.sources.map(item => <button type="button" key={item.id}
      className={`source-tab ${item.id === source?.id ? "selected" : ""}`} aria-pressed={item.id === source?.id}
      onClick={() => { onSelect(item.id); setError(""); }}>
      <Icon name={item.kind === "eight_sleep" ? "bed" : item.metric === "heart_rate" ? "heart" : "air"}/>
      <span><strong>{item.name}</strong><small>{sourceStatus(item, collectorOnline, now)}</small></span>
    </button>)}</div>
    {!source ? <p className="empty-note">{data ? "暂无数据源。开启手环心率广播，或连接环境监测设备后，采集服务会自动发现。" : "正在读取采集服务状态…"}</p> : <>
      <div className="explorer-heading"><div><p className="eyebrow">采集与历史记录</p><h3>{source.name}</h3></div>
        <button className="button" onClick={toggle} disabled={busy || switching}>{busy ? "正在保存…" : switching ? "正在切换…" : source.enabled ? "暂停采集" : "开始采集"}</button>
      </div>
      {(error || source.error) && <p className="notice" role="alert">{error || source.error}</p>}
      {multi && <div className="metric-select"><label htmlFor="detail-metric">查看指标</label><select id="detail-metric" value={key} onChange={e => (isEight ? setEightMetric : setAirMetric)(e.target.value)}>{available.map(k => <option key={k} value={k}>{definitions[k]?.label ?? k}</option>)}</select><span>{isEight ? "云端记录，可能延迟更新" : "切换指标仅影响展示"}</span></div>}
      <div className="detail-stats">
        <div><span>{isEight || !live ? "最近" : "实时"}{label}</span><strong>{isEight && eightMetrics[key]?.approximate && value != null ? "≈" : ""}{displayNumber(value)} <small>{unit}</small></strong><p>{displayTime(valueTime, true)} 收到{live ? "" : " · 历史读数"}</p></div>
        <div><span>{isEight ? "云端同步间隔" : "实际采集频率"}</span><strong>{isEight ? "10" : hz === null ? "—" : hz.toFixed(2)} <small>{isEight ? "秒" : "Hz"}</small></strong><p>{isEight ? "完整快照持续保存" : hz ? `平均 ${(1 / hz).toFixed(2)} 秒一次` : "等待连续样本"}</p></div>
        <div><span>{isHeart ? "当前测量状态" : "累计样本"}</span><strong className="text-stat">{isHeart ? (source.enabled && collectorOnline && source.status === "waiting" ? "等待有效心率" : heartRateStatus(source.latest_value, source.latest_metadata, live)) : Number(source.sample_count).toLocaleString()}</strong><p>{isHeart ? "接触标记不等同于实际佩戴" : "记录保存在本机"}</p></div>
      </div>
      <div className="detail-trend"><div className="detail-section-title"><h4>数据趋势</h4><span>最近 {samples.length} 个样本 · 接收时间</span></div><Sparkline points={samples.map(s => ({ time: s.recorded_at, value: s.value }))} large/><div className="trend-times"><span>{displayTime(samples[0]?.recorded_at, true)}</span><span>{displayTime(samples.at(-1)?.recorded_at, true)}</span></div></div>
      <div className="detail-section-title"><h4>最近记录</h4><span>{isEight ? "每次同步的云端快照" : "最近 8 条"}</span></div>
      <div className="table-wrap"><table><thead><tr><th>接收时间</th><th>{label}</th><th>{isHeart ? "当时测量状态" : "记录状态"}</th></tr></thead><tbody>{samples.length ? samples.slice(-8).reverse().map(s => <tr key={s.id}><td>{displayTime(s.recorded_at, true)}</td><td>{isEight && eightMetrics[key]?.approximate && s.value !== null ? "≈" : ""}{displayNumber(s.value)} <span className="muted">{unit}</span></td><td>{isHeart ? heartRateStatus(s.value, s.metadata) : "已保存"}</td></tr>) : <tr><td colSpan={3} className="empty-note">暂无采集记录</td></tr>}</tbody></table></div>
      {isEight && <p className="detail-note">历史已保存 {Number(data?.history?.days ?? 0).toLocaleString()} 个用户日{data?.history?.first_day ? ` · ${data.history.first_day} 至 ${data.history.last_day}` : ""}{data?.history?.users_total !== "0" && data?.history?.users_total === data?.history?.users_complete ? " · 历史补采完成" : " · 正在检查历史记录"}。当前床温由在线设备的传感器档位按上游换算表得到，属于近似值；原始档位仍保留。睡眠床温来自独立的睡眠记录。</p>}
      <details className="raw-data"><summary>{isHeart ? "原始心率数据" : "完整采集数据"}{isAir ? ` · ${Object.keys(payload ?? {}).length} 个字段` : ""}</summary>
        <p>{isHeart ? "仅保存有效心率及其原始接触标记。0 值和无效通知直接跳过入库；历史旧记录仍保留。" : isEight ? "保留各接口返回与不可用原因。PodOffline 表示云端报告设备离线，404 不能用于判断硬件是否存在。" : "每次轮询保存完整读数；设备更新较慢时，相邻记录可能相同。VOC 与 NOx 为相对指数。"}</p>
        <pre>{JSON.stringify(isEight ? { responses: source.latest_metadata?.responses ?? {}, unavailable: source.latest_metadata?.errors ?? {} } : isAir ? payload ?? {} : source.latest_metadata ?? {}, null, 2)}</pre>
      </details>
    </>}
  </div>;
}
