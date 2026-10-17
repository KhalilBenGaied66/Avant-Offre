import type { ReactNode } from "react";
import type { Brief } from "../types";

// Renders the brief's Markdown subset (## headings, "- " bullets) and turns [F3] citations into
// buttons that highlight the cited fact.
function withCitations(text: string, onCite: (id: string) => void): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /\[(F\d+(?:\s*[,;]\s*F\d+)*)\]/g;
  let last = 0;
  for (const m of text.matchAll(re)) {
    out.push(text.slice(last, m.index));
    const ids = (m[1] ?? "").split(/[,;]/).map((s) => s.trim());
    out.push(
      <span key={`${m.index}`} className="cites">
        {ids.map((id) => (
          <button key={id} className="cite" onClick={() => onCite(id)} title="Voir le fait cité">
            {id}
          </button>
        ))}
      </span>,
    );
    last = (m.index ?? 0) + m[0].length;
  }
  out.push(text.slice(last));
  return out;
}

const FALLBACK_LABELS: Record<string, string> = {
  template: "choix par défaut",
  llm_unavailable: "modèle de langage non configuré",
  llm_stop: "réponse du modèle interrompue",
  verifier: "chiffres non conformes aux faits",
};

function fallbackLabel(reason: string | null): string {
  const code = (reason ?? "").split(/[:]/)[0] ?? "";
  return FALLBACK_LABELS[code] ?? "raison inconnue";
}

export default function BriefView({ brief, onCite }: { brief: Brief; onCite: (id: string) => void }) {
  const blocks: ReactNode[] = [];
  let bullets: string[] = [];
  const flush = () => {
    if (bullets.length) {
      blocks.push(
        <ul key={`ul-${blocks.length}`}>
          {bullets.map((b, i) => (
            <li key={i}>{withCitations(b, onCite)}</li>
          ))}
        </ul>,
      );
      bullets = [];
    }
  };
  for (const raw of brief.text.split("\n")) {
    const line = raw.trim();
    if (!line) continue;
    if (line.startsWith("## ")) {
      flush();
      blocks.push(<h4 key={`h-${blocks.length}`}>{line.slice(3)}</h4>);
    } else if (line.startsWith("- ")) {
      bullets.push(line.slice(2));
    } else {
      flush();
      blocks.push(<p key={`p-${blocks.length}`}>{withCitations(line, onCite)}</p>);
    }
  }
  flush();
  return (
    <div className="brief">
      <p className="muted">
        {brief.fallback ? (
          <span title={brief.fallback_reason ?? ""}>Note déterministe ({fallbackLabel(brief.fallback_reason)}).</span>
        ) : (
          `Rédigée par ${brief.model ?? "—"}, chiffres vérifiés contre les faits.`
        )}
        {brief.removed.length > 0 && ` ${brief.removed.length} phrase(s) retirée(s) par le vérificateur.`}
      </p>
      {blocks}
    </div>
  );
}
