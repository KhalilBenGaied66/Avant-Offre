import { useState } from "react";
import { api } from "../api";

export default function FeedbackPanel({ noticeId, siret }: { noticeId: string; siret: string }) {
  const [reason, setReason] = useState("");
  const [status, setStatus] = useState<string | null>(null);

  const send = (kind: "relevance" | "decision", value: "relevant" | "not_relevant" | "go" | "no_go") => {
    setStatus("Enregistrement…");
    api
      .feedback({ notice_id: noticeId, siret: siret || undefined, kind, value, reason: reason || undefined })
      .then(() => setStatus("Enregistré. Merci."))
      .catch((e: unknown) => setStatus(`Erreur : ${String(e)}`));
  };

  return (
    <div className="feedback">
      <div className="row">
        <span>Cet avis est-il pertinent ?</span>
        <button onClick={() => send("relevance", "relevant")}>Pertinent</button>
        <button onClick={() => send("relevance", "not_relevant")}>Non pertinent</button>
      </div>
      <div className="row">
        <span>Décision du comité :</span>
        <button className="go" onClick={() => send("decision", "go")}>
          GO
        </button>
        <button className="nogo" onClick={() => send("decision", "no_go")}>
          NO-GO
        </button>
      </div>
      <label>
        Motif (facultatif)
        <textarea value={reason} onChange={(e) => setReason(e.target.value)} maxLength={2000} rows={2} />
      </label>
      {status && <p className="muted">{status}</p>}
    </div>
  );
}
