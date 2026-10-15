// Thin typed client. The API key is added by the dev proxy / reverse proxy, never here.
import type { Award, Brief, MarketIntel, Score, Shortlist, Tender } from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (body.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

const q = (params: Record<string, string | undefined>) => {
  const s = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v) s.set(k, v);
  const str = s.toString();
  return str ? `?${str}` : "";
};

export const api = {
  shortlist: (siret: string, week?: string) => call<Shortlist>(`/tenders${q({ siret, week })}`),
  tender: (id: string) => call<Tender>(`/tenders/${encodeURIComponent(id)}`),
  intel: (id: string, siret?: string) =>
    call<MarketIntel>(`/tenders/${encodeURIComponent(id)}/intel${q({ siret })}`),
  score: (id: string, siret?: string) =>
    call<Score>(`/tenders/${encodeURIComponent(id)}/score${q({ siret })}`),
  brief: (id: string, siret: string) =>
    call<Brief>(`/tenders/${encodeURIComponent(id)}/brief${q({ siret })}`, { method: "POST" }),
  awards: (uids: string[]) => call<Award[]>(`/awards${q({ uids: uids.slice(0, 200).join(",") })}`),
  feedback: (body: {
    notice_id: string;
    siret?: string;
    kind: "relevance" | "decision";
    value: "relevant" | "not_relevant" | "go" | "no_go";
    reason?: string;
  }) => call<{ feedback_id: string }>("/feedback", { method: "POST", body: JSON.stringify(body) }),
};
