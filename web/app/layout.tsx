import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "4seas · 房间看板",
  description: "查看房间环境、身体变化与每位体验者的采集记录。",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN" data-theme="dark">
      <body>{children}</body>
    </html>
  );
}
