import { useEffect, useState } from "react";
import { api, ApiError } from "../api";
import { dayBefore, daysUntil, fmtDate } from "../format";
import { go } from "../router";
import type { Shortlist } from "../types";
import BandChip from "./BandChip";

export default function ShortlistPage({ siret, week }: { siret: string; week: string }) {
  const [form, setForm] = useState({ siret, week });
  const [data, setData] = useState<Shortlist | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!siret) return;
    setLoading(true);
    setError(null);
    api
      .shortlist(siret, week || undefined)
      .then(setData)
      .catch((e: unknown) => setError(e instanceof ApiError ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [siret, week]);

  return (
    <section>
      <h1>Sélection de la semaine</h1>
      <form
        className="search"
        onSubmit={(e) => {
          e.preventDefault();
          go("/", { siret: form.siret.trim(), week: form.week.trim() || undefined });
        }}
      >
        <label>
          SIRET ou SIREN
          <input
            value={form.siret}
            onChange={(e) => setForm({ ...form, siret: e.target.value })}
            placeholder="ex. 12345678200017"
            required
          />
        </label>
        <label>
          Semaine (facultatif)
          <input
            value={form.week}
            onChange={(e) => setForm({ ...form, week: e.target.value })}
            placeholder="AAAA-Www, ex. 2026-W42"
            pattern="\d{4}-W\d{2}"
          />
        </label>
        <button type="submit">Afficher</button>
      </form>

      {loading && <p className="muted">Chargement…</p>}
      {error && <p className="error">{error}</p>}

      {data && !loading && (
        <>
          <p className="muted">
            Avis publiés du {fmtDate(data.week_start)} au {dayBefore(data.week_end)} : {data.eligible.length} éligibles,{" "}
            {data.excluded.length} exclus.
          </p>
          <table className="grid">
            <thead>
              <tr>
                <th>#</th>
                <th>Bande</th>
                <th>Date limite</th>
                <th>Acheteur</th>
                <th>Objet</th>
                <th title="Part des autres avis de la semaine moins bien classés pour ce profil">Adéquation</th>
              </tr>
            </thead>
            <tbody>
              {data.eligible.map((t) => {
                const days = daysUntil(t.deadline_on, data.as_of);
                const why = t.explanations
                  .map((e) => `• ${e.objet}${e.notified_on ? ` (${fmtDate(e.notified_on)})` : ""}`)
                  .join("\n");
                return (
                  <tr key={t.notice_id} className="clickable" onClick={() => go(`/tender/${encodeURIComponent(t.notice_id)}`, { siret })}>
                    <td>{t.rank}</td>
                    <td>
                      {t.band ? (
                        <BandChip band={t.band} />
                      ) : (
                        <span className="muted" title="Grille calculée à l'ouverture de l'avis">—</span>
                      )}
                    </td>
                    <td>
                      {fmtDate(t.deadline_on)}
                      {days != null && <span className="muted"> · J-{days}</span>}
                    </td>
                    <td>{t.buyer_name ?? "—"}</td>
                    <td title={why ? `Contrats passés les plus proches :\n${why}` : "Profil sans historique"}>
                      {t.objet ?? t.notice_id}
                    </td>
                    <td>{Math.round(t.fit_percentile * 100)} %</td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          {data.excluded.length > 0 && (
            <details className="excluded">
              <summary>Avis exclus ({data.excluded.length})</summary>
              <ul>
                {data.excluded.map((e) => (
                  <li key={e.notice_id}>
                    <strong>{e.objet ?? e.notice_id}</strong> — {e.labels.join(" ; ")}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </>
      )}
    </section>
  );
}
