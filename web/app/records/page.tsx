import { RecordsList } from "@/components/records-list";
import { Starfield } from "@/components/room-ui";
import Link from "next/link";
import "@/app/display.css";

export default async function RecordsPage({ searchParams }: {
  searchParams: Promise<{ before?: string }>;
}) {
  const { before } = await searchParams;
  return <><Starfield/><main className="report-page records-page">
    <header><span>4seas ✦</span><h1>历史记录</h1><Link className="text-button" href="/">返回体验</Link></header>
    <RecordsList key={before ?? "latest"} before={before}/>
  </main></>;
}
