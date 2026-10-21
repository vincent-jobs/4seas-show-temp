export function experienceName(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const name = value.trim();
  return Array.from(name).length >= 1 && Array.from(name).length <= 60
    && !/[\u0000-\u001f\u007f]/.test(name) ? name : null;
}

export function validExperienceId(id: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id);
}

export function sameOrigin(request: Request): boolean {
  const origin = request.headers.get("origin");
  if (!origin) return true;
  try { return new URL(origin).host === request.headers.get("host"); }
  catch { return false; }
}

// Start/end and Store.write share this transaction lock. Boundaries use the
// database clock after acquiring it; delayed samples use their reception time.
export const EXPERIENCE_LOCK = 746201;
