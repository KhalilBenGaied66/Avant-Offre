// Presentation only: values are computed server-side; these helpers only format them.
const eur = new Intl.NumberFormat("fr-FR", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });
const int = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 0 });

export const fmtEur = (v: number | null | undefined) => (v == null ? "—" : eur.format(v));
export const fmtInt = (v: number | null | undefined) => (v == null ? "—" : int.format(v));
export const fmtPct = (v: number | null | undefined) => (v == null ? "—" : `${int.format(v)} %`);
export const fmtDate = (iso: string | null | undefined) =>
  iso ? new Date(`${iso}T00:00:00`).toLocaleDateString("fr-FR") : "—";
// Whole days from the server's reference day (`as_of`: today, or a demo snapshot's date) to a
// date: same arithmetic as the server.
export const daysUntil = (iso: string | null | undefined, asOf?: string | null) => {
  if (!iso) return null;
  const from = asOf ? new Date(`${asOf}T00:00:00`) : new Date();
  from.setHours(0, 0, 0, 0);
  return Math.round((new Date(`${iso}T00:00:00`).getTime() - from.getTime()) / 86_400_000);
};

export const dayBefore = (iso: string) => {
  const d = new Date(`${iso}T00:00:00`);
  d.setDate(d.getDate() - 1);
  return d.toLocaleDateString("fr-FR");
};
