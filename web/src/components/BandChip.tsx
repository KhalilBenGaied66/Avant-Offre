import type { Band } from "../types";

const LABEL: Record<Band, string> = { GO: "GO", REVIEW: "À ÉTUDIER", "NO-GO": "NO-GO" };

export default function BandChip({ band }: { band: Band }) {
  return (
    <span className={`chip chip-${band.toLowerCase()}`} title={`Bande de la grille : ${band}`}>
      {LABEL[band]}
    </span>
  );
}
