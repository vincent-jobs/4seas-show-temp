import { pool } from "@/lib/db";
import { EXPERIENCE_LOCK, experienceName, sameOrigin, validExperienceId } from "@/lib/experiences";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const cursor = new URL(request.url).searchParams.get("before");
  if (cursor && !validExperienceId(cursor)) {
    return Response.json({ error: "分页参数无效。" }, { status: 400 });
  }
  try {
    const result = await pool.query(
      `WITH numbered AS (
         SELECT e.*, row_number() OVER (ORDER BY started_at, id)::text AS sequence FROM experiences e
       )
       SELECT e.*, (SELECT count(*)::text FROM experience_samples WHERE experience_id=e.id) AS sample_count
       FROM numbered e WHERE ($1::uuid IS NULL OR (e.started_at,e.id) <
         (SELECT started_at,id FROM experiences WHERE id=$1))
       ORDER BY e.started_at DESC,e.id DESC LIMIT 101`, [cursor]);
    return Response.json({ experiences: result.rows.slice(0, 100),
      next: result.rows.length > 100 ? result.rows[99].id : null },
      { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    console.error("Experience list failed", error);
    return Response.json({ error: "暂时无法读取体验记录。" }, { status: 503 });
  }
}

export async function POST(request: Request) {
  if (!sameOrigin(request)) return Response.json({ error: "请在本应用页面内操作。" }, { status: 403 });
  let body;
  try { body = await request.json(); }
  catch { return Response.json({ error: "请求格式无效。" }, { status: 400 }); }
  const name = experienceName(body?.name);
  if (!name) return Response.json({ error: "请输入 1–60 个字的体验者名字。" }, { status: 400 });
  const clientId = body?.client_id, sourceId = body?.heart_source_id;
  if (typeof clientId !== "string" || !validExperienceId(clientId) || typeof sourceId !== "string" || !sourceId) {
    return Response.json({ error: "请选择手环后开始体验。" }, { status: 400 });
  }
  try {
    const client = await pool.connect();
    try {
      await client.query("BEGIN");
      await client.query("SELECT pg_advisory_xact_lock($1)", [EXPERIENCE_LOCK]);
      const own = await client.query("SELECT * FROM experiences WHERE client_id=$1 AND ended_at IS NULL", [clientId]);
      if (own.rowCount) {
        await client.query("COMMIT");
        return Response.json(own.rows[0]);
      }
      const band = await client.query("SELECT id, last_seen > clock_timestamp() - interval '60 seconds' AS reachable FROM sources WHERE id=$1 AND kind='ble_heart_rate' FOR UPDATE", [sourceId]);
      if (!band.rowCount) {
        await client.query("ROLLBACK");
        return Response.json({ error: "这只手环不可用，请重新选择。" }, { status: 400 });
      }
      const occupied = await client.query("SELECT id FROM experiences WHERE heart_source_id=$1 AND ended_at IS NULL", [sourceId]);
      if (occupied.rowCount) {
        await client.query("ROLLBACK");
        return Response.json({ error: "这只手环正在体验中，请选择其他手环。" }, { status: 409 });
      }
      if (!band.rows[0].reachable) {
        await client.query("ROLLBACK");
        return Response.json({ error: "暂时找不到这只手环，请开启心率广播后重试。" }, { status: 409 });
      }
      await client.query("UPDATE sources SET enabled=true WHERE id=$1", [sourceId]);
      const result = await client.query(
        "INSERT INTO experiences (name,client_id,heart_source_id) VALUES ($1,$2,$3) RETURNING *",
        [name, clientId, sourceId]);
      await client.query("COMMIT");
      return Response.json(result.rows[0], { status: 201 });
    } catch (error) { await client.query("ROLLBACK"); throw error; }
    finally { client.release(); }
  } catch (error) {
    console.error("Experience start failed", error);
    return Response.json({ error: "开始体验失败，请刷新后重试。" }, { status: 503 });
  }
}
