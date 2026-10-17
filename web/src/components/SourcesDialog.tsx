import { useEffect, useState } from "react";
import { api } from "../api";
import { fmtDate, fmtEur } from "../format";
import type { Award } from "../types";

export default function SourcesDialog({ title, uids, onClose }: { title: string; uids: string[]; onClose: () => void }) {
  const [rows, setRows] = useState<Award[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.awards(uids).then(setRows).catch((e: unknown) => setError(String(e)));
  }, [uids]);

  return (
    <div className="overlay" role="dialog" aria-modal="true" aria-label={title} onClick={onClose}>
      <div className="dialog" onClick={(e) => e.stopPropagation()}>
        <div className="dialog-head">
          <h3>Sources : {title}</h3>
          <button onClick={onClose} aria-label="Fermer">
            ✕
          </button>
        </div>
        <p className="muted">
          {uids.length} contrat(s) attribué(s) — données essentielles de la commande publique (DECP).
          {uids.length > 200 && " Les 200 premiers sont affichés."}
        </p>
        {error && <p className="error">{error}</p>}
        {!rows && !error && <p className="muted">Chargement…</p>}
        {rows && rows.length === 0 && <p className="muted">Aucun contrat attribué correspondant.</p>}
        {rows && rows.length > 0 && (
          <table className="grid compact">
            <thead>
              <tr>
                <th>Notifié le</th>
                <th>Acheteur</th>
                <th>Objet</th>
                <th>Montant</th>
                <th>Titulaire(s)</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((a) => (
                <tr key={a.uid}>
                  <td>{fmtDate(a.notified_on)}</td>
                  <td>{a.buyer_name ?? "—"}</td>
                  <td>{a.objet ?? "—"}</td>
                  <td>{a.is_framework ? "accord-cadre" : fmtEur(a.amount_eur)}</td>
                  <td>{a.winners?.join(", ") ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
