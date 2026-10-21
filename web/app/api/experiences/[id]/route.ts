import { pool } from "@/lib/db";
import { EXPERIENCE_LOCK, sameOrigin, validExperienceId } from "@/lib/experiences";

export const dynamic = "force-dynamic";
type Context = { params: Promise<{ id: string }> };

export async function GET(request: Request, context: Context) {
  const { id } = await context.params;
  if (!validExperienceId(id)) return Response.json({ error: "体验编号无效。" }, { status: 400 });
  const query = new URL(request.url).searchParams;
  const source = query.get("source"), before = query.get("before");
  if (before && (!/^[1-9]\d{0,18}$/.test(before) || BigInt(before) > BigInt("9223372036854775807"))) {
    return Response.json({ error: "分页参数无效。" }, { status: 400 });
  }
  try {
    const [experience, sources, samples] = await Promise.all([
      pool.query("SELECT e.*,s.name AS heart_source_name FROM experiences e LEFT JOIN sources s ON s.id=e.heart_source_id WHERE e.id=$1", [id]),
      pool.query(`SELECT s.id,s.name,s.kind,s.unit,count(*)::text AS sample_count
        FROM experience_samples x JOIN samples p ON p.id=x.sample_id JOIN sources s ON s.id=p.source_id WHERE x.experience_id=$1
        GROUP BY s.id ORDER BY s.name,s.id`, [id]),
      pool.query(`SELECT p.id,p.source_id,s.name AS source_name,s.kind,s.unit,p.value,p.recorded_at,
        p.metadata - 'responses' AS metadata FROM experience_samples x JOIN samples p ON p.id=x.sample_id JOIN sources s ON s.id=p.source_id
        WHERE x.experience_id=$1 AND ($2::text IS NULL OR source_id=$2)
        AND ($3::bigint IS NULL OR p.id<$3)
        ORDER BY p.id DESC LIMIT 51`, [id, source, before]),
    ]);
    if (!experience.rowCount) return Response.json({ error: "没有找到这次体验。" }, { status: 404 });
    return Response.json({ experience: experience.rows[0], sources: sources.rows,
      samples: samples.rows.slice(0, 50), next: samples.rows.length > 50 ? samples.rows[49].id : null },
      { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    console.error("Experience records failed", error);
    return Response.json({ error: "读取体验数据失败，请稍后重试。" }, { status: 503 });
  }
}

export async function PATCH(request: Request, context: Context) {
  if (!sameOrigin(request)) return Response.json({ error: "请在本应用页面内操作。" }, { status: 403 });
  const { id } = await context.params;
  if (!validExperienceId(id)) return Response.json({ error: "体验编号无效。" }, { status: 400 });
  let body;
  try { body = await request.json(); } catch { return Response.json({ error: "请求格式无效。" }, { status: 400 }); }
  if (typeof body?.client_id !== "string" || !validExperienceId(body.client_id)) return Response.json({ error: "客户端编号无效。" }, { status: 400 });
  try {
    const client = await pool.connect();
    try {
      await client.query("BEGIN");
      await client.query("SELECT pg_advisory_xact_lock($1)", [EXPERIENCE_LOCK]);
      // Idempotent: retrying after a lost response must not extend the interval.
      const result = await client.query(`UPDATE experiences SET ended_at=COALESCE(ended_at,clock_timestamp())
        WHERE id=$1 AND client_id=$2 RETURNING *`, [id, body.client_id]);
      await client.query("COMMIT");
      if (!result.rowCount) return Response.json({ error: "没有找到这次体验。" }, { status: 404 });
      return Response.json(result.rows[0]);
    } catch (error) { await client.query("ROLLBACK"); throw error; }
    finally { client.release(); }
  } catch (error) {
    console.error("Experience end failed", error);
    return Response.json({ error: "结束体验失败，请刷新后重试。" }, { status: 503 });
  }
}
