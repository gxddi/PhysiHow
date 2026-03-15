/**
 * REST client for PhysiHow: exercise catalog and health.
 */
const DEFAULT_BASE = "";

export interface ExerciseListItem {
  slug: string;
  name: string;
  url: string;
}

export interface ExerciseDetail {
  slug: string;
  name: string;
  url: string;
  technique: string;
  targetMuscles: string;
  introduction: string;
  fullText: string;
}

export async function healthCheck(baseUrl: string = DEFAULT_BASE): Promise<{ status: string }> {
  const res = await fetch(`${baseUrl}/api/health`, { signal: AbortSignal.timeout(5000) });
  const data = (await res.json()) as { status?: string };
  if (!res.ok) throw new Error((data as { detail?: string })?.detail ?? res.statusText);
  return data as { status: string };
}

export async function listExercises(baseUrl: string = DEFAULT_BASE): Promise<{ exercises: ExerciseListItem[] }> {
  const res = await fetch(`${baseUrl}/api/exercises`, { signal: AbortSignal.timeout(10000) });
  if (!res.ok) {
    const text = await res.text();
    const hint =
      res.status === 502
        ? " Is the API running? Start it with: uvicorn api.main:app --reload --port 8000"
        : "";
    throw new Error(`Exercises API error ${res.status}: ${text || res.statusText}${hint}`);
  }
  return res.json() as Promise<{ exercises: ExerciseListItem[] }>;
}

export async function getExerciseBySlug(
  slug: string,
  baseUrl: string = DEFAULT_BASE
): Promise<ExerciseDetail> {
  const res = await fetch(`${baseUrl}/api/exercises/${encodeURIComponent(slug)}`, {
    signal: AbortSignal.timeout(5000),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Exercise API error ${res.status}: ${text || res.statusText}`);
  }
  return res.json() as Promise<ExerciseDetail>;
}

export interface ChatTurn {
  role: "user" | "model";
  text: string;
}

export async function sendCoachMessage(
  exerciseSlug: string,
  message: string,
  history: ChatTurn[],
  baseUrl: string = DEFAULT_BASE
): Promise<{ reply: string }> {
  const res = await fetch(`${baseUrl}/api/coach/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      exercise_slug: exerciseSlug,
      message,
      history: history.map((t) => ({ role: t.role, text: t.text })),
    }),
    signal: AbortSignal.timeout(60000),
  });
  if (!res.ok) {
    const text = await res.text();
    let detail = text;
    try {
      const j = JSON.parse(text) as { detail?: string };
      detail = j.detail ?? text;
    } catch {
      // use raw text
    }
    throw new Error(detail || res.statusText);
  }
  return res.json() as Promise<{ reply: string }>;
}
