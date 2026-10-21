"use client";
import { useEffect, useRef, useState } from "react";
import QRCode from "qrcode";
import type { Experience } from "@/lib/types";

export function ExperienceReceipt({ experience, onClose }: { experience: Experience; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [image, setImage] = useState("");
  const [url, setUrl] = useState("");
  useEffect(() => {
    dialog.current?.showModal();
    const target = experience.id;
    setUrl(`/experience/${experience.id}`);
    let disposed = false;
    void QRCode.toCanvas(target, { width: 640, margin: 4, errorCorrectionLevel: "M" }).then(qr => {
      const canvas = document.createElement("canvas"); canvas.width = 800; canvas.height = 1020;
      const ctx = canvas.getContext("2d")!;
      ctx.fillStyle = "#fffdf7"; ctx.fillRect(0, 0, 800, 1020);
      ctx.textAlign = "center"; ctx.fillStyle = "#183a32"; ctx.font = "28px sans-serif";
      ctx.fillText("4seas · 体验记录", 400, 70);
      ctx.font = "bold 38px sans-serif"; ctx.fillText(experience.name, 400, 140, 700);
      ctx.drawImage(qr, 80, 180);
      ctx.font = "22px sans-serif";
      ctx.fillText(new Date(experience.started_at).toLocaleString("zh-CN", { hour12: false }), 400, 870);
      ctx.font = "20px monospace"; ctx.fillText(experience.id, 400, 930, 740);
      if (!disposed) setImage(canvas.toDataURL("image/png"));
    });
    return () => { disposed = true; };
  }, [experience]);
  return <dialog className="receipt-dialog" ref={dialog} onCancel={onClose}>
    <button className="receipt-close" onClick={onClose} aria-label="关闭二维码">×</button>
    {image ? <img src={image} alt={`${experience.name}的体验记录二维码`} className="receipt-image"/> : <p>正在生成二维码…</p>}
    <code className="receipt-uuid">{experience.id}</code>
    <div className="receipt-actions">
      <a className="button primary" href={image || undefined} download={`4seas-${experience.name}.png`}>保存图片</a>
      <a className="button" href={url || undefined} target="_blank" rel="noreferrer">查看记录</a>
    </div>
  </dialog>;
}
