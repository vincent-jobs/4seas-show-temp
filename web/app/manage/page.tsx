"use client";

import { useRoom } from "@/lib/use-room";
import { ExperiencePanel } from "@/components/experience-panel";
import { SourceExplorer } from "@/components/source-explorer";
import { Icon, Starfield } from "@/components/room-ui";

export default function ManagePage() {
  const room = useRoom();
  return <>
    <Starfield/>
    <main className="room-shell"><div className="room-panel">
      <header className="room-header">
        <div className="room-title"><p className="eyebrow">4seas · 工作人员</p><h1>体验与采集管理</h1></div>
        <a className="button" href="/">返回展示</a>
      </header>
      {(room.error || room.data?.collector?.error) && <p className="notice" role="alert">{room.error || room.data?.collector?.error}</p>}
      <ExperiencePanel active={room.data?.experience} sources={room.data?.sources ?? []} clientId={room.clientId} onSelect={room.setSelected} now={room.now} ready={!!room.data && !room.error} onChanged={room.refresh}/>
      <section className="source-explorer" aria-label="数据源与采集记录">
        <div className="manage-heading"><Icon name="sliders"/><h2>数据源与采集记录</h2></div>
        <SourceExplorer data={room.data} selected={room.selected} now={room.now}
          collectorOnline={room.collectorOnline} onSelect={room.setSelected} onChanged={room.refresh}/>
      </section>
    </div></main>
  </>;
}
