import { pool } from "@/lib/db";
import { validExperienceId } from "@/lib/experiences";
export const dynamic = "force-dynamic";

export async function GET(_request: Request, context: { params: Promise<{ id: string }> }) {
  const { id } = await context.params;
  if (!validExperienceId(id)) return Response.json({ error: "记录不存在" }, { status: 404 });
  try {
    const [experience, summary, heart, room] = await Promise.all([
      pool.query(`SELECT e.id,e.name,e.started_at,e.ended_at,s.name AS band_name FROM experiences e
        LEFT JOIN sources s ON s.id=e.heart_source_id WHERE e.id=$1`, [id]),
      pool.query(`SELECT s.kind,count(*)::text AS count,round(avg(p.value)::numeric,1) AS average,
        min(p.value) AS minimum,max(p.value) AS maximum
        FROM experience_samples x JOIN samples p ON p.id=x.sample_id JOIN sources s ON s.id=p.source_id
        WHERE x.experience_id=$1 GROUP BY s.kind`, [id]),
      pool.query(`WITH ranked AS (
        SELECT p.recorded_at,p.value,row_number() OVER (ORDER BY p.recorded_at,p.id) AS n,
          count(*) OVER () AS total FROM experience_samples x JOIN samples p ON p.id=x.sample_id
          JOIN sources s ON s.id=p.source_id
        WHERE x.experience_id=$1 AND s.kind='ble_heart_rate' AND p.value>0
      ) SELECT recorded_at,value FROM ranked
        WHERE mod(n-1,greatest(1,ceil(total/240.0)::bigint))=0 OR n=total ORDER BY recorded_at`, [id]),
      pool.query(`SELECT DISTINCT ON (s.kind) s.kind,p.recorded_at,p.metadata - 'responses' AS metadata
        FROM experience_samples x JOIN samples p ON p.id=x.sample_id JOIN sources s ON s.id=p.source_id
        WHERE x.experience_id=$1 AND s.kind IN ('airgradient','eight_sleep')
        ORDER BY s.kind,p.recorded_at DESC,p.id DESC`, [id]),
    ]);
    if (!experience.rowCount) return Response.json({ error: "记录不存在" }, { status: 404 });
    return Response.json({ experience: experience.rows[0], summary: summary.rows, heart: heart.rows, room: room.rows },
      { headers: { "Cache-Control": "no-store", "Referrer-Policy": "no-referrer" } });
  } catch {
    return Response.json({ error: "暂时无法读取记录" }, { status: 503 });
  }
}
