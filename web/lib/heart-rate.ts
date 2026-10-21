import type { Sample, Source } from "./types";

type Metadata = Sample["metadata"] | null | undefined;

export function heartRateValue(value: number | null | undefined, metadata: Metadata): number | null {
  // Also handles older samples saved before the collector began marking invalid readings.
  return typeof value === "number" && Number.isFinite(value) && value > 0
    && metadata?.contact !== false && metadata?.measurement_valid !== false
    ? value : null;
}

export function heartRateStatus(value: number | null | undefined, metadata: Metadata, current = true): string {
  if (!current) return "状态未知";
  if (metadata?.contact === false) return "未接触";
  if (heartRateValue(value, metadata) === null) return "无有效心率";
  return metadata?.contact === true ? "设备报告接触" : "接触状态未提供";
}


// Advertisements or live notifications keep last_seen fresh, including 0 bpm.
// Persisted status strings alone do not prove that a band is still reachable.
export function availableHeartBand(source: Source, now: number): boolean {
  return source.kind === "ble_heart_rate" && !source.occupied
    && Number.isFinite(Date.parse(source.last_seen))
    && now - Date.parse(source.last_seen) < 60000;
}
