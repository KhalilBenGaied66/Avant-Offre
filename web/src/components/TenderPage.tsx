import { useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../api";
import { daysUntil, fmtDate, fmtEur, fmtInt, fmtPct } from "../format";
import { go } from "../router";
import type { Brief, MarketIntel, Score, Tender } from "../types";
import BandChip from "./BandChip";
import BriefView from "./BriefView";
import FeedbackPanel from "./FeedbackPanel";
import SourcesDialog from "./SourcesDialog";

interface Row {
  id: string;
  label: string;
  value: string;
  sources: string[];
}

function intelRows(intel: MarketIntel): Row[] {
  const rows: Row[] = [];
  const add = (id: string, label: string, value: string, sources: string[]) => rows.push({ id, label, value, sources });
  add("n", "Contrats comparables analysés", fmtInt(intel.n_comparables), []);
  intel.competitors.slice(0, 5).forEach((c, i) => {
    const flag = c.incumbent_with_buyer ? " · déjà titulaire chez l'acheteur" : c.new_to_buyer ? " · nouveau chez l'acheteur" : "";
    add(`c${i}`, `Concurrent probable n°${i + 1}`, `${c.name} — ${c.comparable_wins} contrat(s) comparable(s)${flag}`, c.sources);
  });
  const s = intel.newcomer_share;
  add("ns", "Part des primo-titulaires", s.value == null ? `non évaluée (${s.note ?? "—"})` : `${fmtPct(s.value)} (n = ${s.n})`, s.sources);
  const p = intel.price_range;
  add(
    "pr",
    "Fourchette de prix P25 – P75 (médiane)",
    p.p50 == null ? `non évaluée (${p.note ?? `n = ${p.n}`})` : `${fmtEur(p.p25)} – ${fmtEur(p.p75)} (${fmtEur(p.p50)}), n = ${p.n}`,
    p.sources,
  );
  const sme = intel.sme_share;
  add("sme", "Part des PME parmi les titulaires", sme.value == null ? "non évaluée" : `${fmtPct(sme.value)} (n = ${sme.n})`, sme.sources);
  const b = intel.bids_received;
  add("bids", "Offres reçues (médiane)", b.value == null ? "non évaluée" : `${fmtInt(b.value)} (n = ${b.n})`, b.sources);
  const bt = intel.buyer_top_winner_share;
  add("bt", "Part de l'acheteur captée par son premier titulaire", bt.value == null ? "non évaluée" : `${fmtPct(bt.value)} (n = ${bt.n})`, bt.sources);
  return rows;
}

export default function TenderPage({ id, siret }: { id: string; siret: string }) {
  const [tender, setTender] = useState<Tender | null>(null);
  const [intel, setIntel] = useState<MarketIntel | null>(null);
  const [score, setScore] = useState<Score | null>(null);
  const [brief, setBrief] = useState<Brief | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [briefLoading, setBriefLoading] = useState(false);
  const [sources, setSources] = useState<{ title: string; uids: string[] } | null>(null);
  const [highlight, setHighlight] = useState<string | null>(null);

  useEffect(() => {
    const fail = (e: unknown) => setError(e instanceof ApiError ? e.message : String(e));
    api.tender(id).then(setTender).catch(fail);
    api.intel(id, siret || undefined).then(setIntel).catch(fail);
    api.score(id, siret || undefined).then(setScore).catch(fail);
  }, [id, siret]);

  const rows: Row[] = useMemo(() => {
    if (brief) return brief.facts.map((f) => ({ id: f.id, label: f.label, value: f.display, sources: f.sources }));
    return intel ? intelRows(intel) : [];
  }, [brief, intel]);

  const cite = (factId: string) => {
    setHighlight(factId);
    document.getElementById(`fact-${factId}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  };

  const days = daysUntil(tender?.deadline_on);
  return (
    <section>
      <button className="link" onClick={() => go("/", { siret })}>
        ← Retour à la sélection
      </button>
      {error && <p className="error">{error}</p>}
      {tender && (
        <div className="tender-head">
          <h1>{tender.objet ?? tender.notice_id}</h1>
          <p className="muted">
            {tender.buyer_name ?? "Acheteur inconnu"} · avis {tender.notice_id} · date limite {fmtDate(tender.deadline_on)}
            {days != null && ` (J-${days})`} · montant estimé {fmtEur(tender.estimated_value_eur)}
            {tender.url && (
              <>
                {" · "}
                <a href={tender.url} target="_blank" rel="noreferrer">
                  avis BOAMP
                </a>
              </>
            )}
          </p>
        </div>
      )}

      <div className="columns">
        <div>
          <h2>Grille go / no-go</h2>
          {score ? (
            <>
              <p>
                <BandChip band={score.band} /> score {score.total == null ? "—" : score.total.toFixed(2).replace(".", ",")} · poids évalués{" "}
                {Math.round(score.assessed_weight * 100)} %
              </p>
              {score.hard_stops.length > 0 && <p className="error">Critère d'arrêt : {score.hard_stops.join(" ; ")}</p>}
              <table className="grid compact">
                <thead>
                  <tr>
                    <th>Critère</th>
                    <th>Poids</th>
                    <th>Valeur (0–1)</th>
                    <th>Remarque</th>
                  </tr>
                </thead>
                <tbody>
                  {score.criteria.map((c) => (
                    <tr key={c.id} className={c.assessed ? "" : "muted"}>
                      <td>{c.label}</td>
                      <td>{Math.round(c.weight * 100)} %</td>
                      <td>{c.value == null ? "non évalué" : c.value.toFixed(2).replace(".", ",")}</td>
                      <td>{c.note ?? ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="muted small">Pondérations définies par le bureau des offres (config/scorecard.yaml).</p>
            </>
          ) : (
            <p className="muted">Calcul…</p>
          )}

          <h2>Faits {brief ? "cités par la note" : "de marché"}</h2>
          <table className="grid compact">
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} id={`fact-${r.id}`} className={highlight === r.id ? "highlight" : ""}>
                  {brief && <td className="mono">{r.id}</td>}
                  <td>{r.label}</td>
                  <td>{r.value}</td>
                  <td>
                    {r.sources.length === 0 || r.sources.every((u) => u === id) ? (
                      <span className="muted small">avis</span>
                    ) : (
                      <button className="link" onClick={() => setSources({ title: r.label, uids: r.sources })}>
                        {r.sources.length} contrat(s)
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div>
          <h2>Note de synthèse</h2>
          {!brief && (
            <button
              disabled={!siret || briefLoading}
              onClick={() => {
                setBriefLoading(true);
                api
                  .brief(id, siret)
                  .then(setBrief)
                  .catch((e: unknown) => setError(String(e)))
                  .finally(() => setBriefLoading(false));
              }}
            >
              {briefLoading ? "Rédaction…" : "Générer la note"}
            </button>
          )}
          {!siret && <p className="muted">Indiquez un SIRET dans la sélection pour générer la note.</p>}
          {brief && <BriefView brief={brief} onCite={cite} />}

          <h2>Votre avis</h2>
          <FeedbackPanel noticeId={id} siret={siret} />
        </div>
      </div>
      {sources && <SourcesDialog title={sources.title} uids={sources.uids} onClose={() => setSources(null)} />}
    </section>
  );
}
