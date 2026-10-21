"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import type { Experience } from "@/lib/types";

type History = { experiences: (Experience & { sequence: string })[]; next: string | null };
const enteredAt = (time: string) => new Date(time).toLocaleString("zh-CN", {
  timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit",
  hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
});

export function RecordsList({ before }: { before?: string }) {
  const [data, setData] = useState<History | null>(null);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    let disposed = false;
    setError("");
    fetch("/api/experiences" + (before ? `?before=${encodeURIComponent(before)}` : ""),
      { signal: controller.signal, cache: "no-store" })
      .then(async response => {
        const body = await response.json();
        if (!response.ok) throw new Error(body.error || "暂时无法读取历史记录");
        return body;
      }).then(result => { if (!disposed) setData(result); })
      .catch(error => { if (!disposed) setError(error.name === "AbortError" ? "读取超时，请重试" : error.message); })
      .finally(() => clearTimeout(timeout));
    return () => { disposed = true; controller.abort(); clearTimeout(timeout); };
  }, [before, revision]);

  return <section aria-label="历史记录列表">
    {error ? <div role="alert" className="records-message">{error} <button className="text-button" onClick={() => setRevision(n => n + 1)}>重试</button></div>
      : !data ? <p className="records-message" role="status">正在读取…</p>
      : data.experiences.length === 0 ? <p className="records-message">暂无记录</p>
      : <div className="records-table-wrap"><table className="records-table">
        <thead><tr><th scope="col">序号</th><th scope="col">名字</th><th scope="col">UUID</th><th scope="col">录入时间</th></tr></thead>
        <tbody>{data.experiences.map(record => {
          const href = `/experience/${record.id}${before ? `?before=${encodeURIComponent(before)}` : ""}`;
          return <tr key={record.id}>
            <td><Link href={href} tabIndex={-1}>{record.sequence}</Link></td>
            <td><Link href={href} className="record-name">{record.name}</Link></td>
            <td><Link href={href} tabIndex={-1} className="record-uuid">{record.id}</Link></td>
            <td><Link href={href} tabIndex={-1}><time dateTime={record.started_at}>{enteredAt(record.started_at)}</time></Link></td>
          </tr>;
        })}</tbody>
      </table></div>}
    <nav className="records-pagination" aria-label="历史记录分页">
      {before && <Link className="text-button" href="/records">最新记录</Link>}
      {data?.next && <Link className="text-button" href={`/records?before=${data.next}`}>更早记录 →</Link>}
    </nav>
  </section>;
}
