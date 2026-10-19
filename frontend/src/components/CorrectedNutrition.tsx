import type { CorrectedPanel } from "@/lib/types";

/** FDA-style Nutrition Facts showing what the panel must say for its printed amounts.
 *  Changed values are highlighted, with the printed value struck through beside them. */
export function CorrectedNutrition({ panel }: { panel: CorrectedPanel }) {
  const calChanged = panel.calories !== null && panel.calories !== panel.calories_printed;
  return (
    <section aria-label="Corrected Nutrition Facts" className="space-y-2">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-faint">Corrected panel (computed)</h3>
      <div className="w-full max-w-xs border-2 border-ink bg-surface p-2 font-sans text-ink">
        <p className="text-2xl font-black leading-none tracking-tight">Nutrition Facts</p>
        <div className="mt-1 border-b-[6px] border-ink pb-1 text-sm">
          {panel.servings_per_container !== null && <p>{panel.servings_per_container} servings per container</p>}
          <p className="flex justify-between font-bold">
            <span>Serving size</span>
            <span className="text-likely" title="Needs a household measure and grams">{panel.printed_serving || "?"} (needs unit)</span>
          </p>
        </div>
        <div className="flex items-end justify-between border-b-4 border-ink py-1">
          <span className="text-xs font-bold">Amount per serving<br /><span className="text-2xl font-black">Calories</span></span>
          <span className={`tabular text-3xl font-black ${calChanged ? "rounded bg-pass-soft px-1 text-pass" : ""}`}>
            {panel.calories ?? panel.calories_printed}
            {calChanged && <s className="ml-1 text-sm font-normal text-ink-faint">{panel.calories_printed}</s>}
          </span>
        </div>
        <p className="border-b border-ink py-0.5 text-right text-xs font-bold">% Daily Value*</p>
        <table className="w-full text-sm">
          <tbody>
            {panel.rows.map((r) => {
              const amountChanged = r.amount !== r.printed_amount;
              const dvChanged = (r.dv ?? "") !== (r.printed_dv ?? "").replace("*", "");
              return (
                <tr key={r.key} className={`border-b border-line-strong ${r.changed ? "bg-pass-soft" : ""}`}>
                  <td className={`py-0.5 ${r.indent ? "pl-3" : "font-bold"}`}>
                    {r.label}{" "}
                    <span className="tabular font-normal">
                      {r.amount}
                      {amountChanged && <s className="ml-1 text-xs text-ink-faint">{r.printed_amount}</s>}
                    </span>
                  </td>
                  <td className="tabular py-0.5 text-right font-bold">
                    {r.dv ?? ""}
                    {dvChanged && r.printed_dv && <s className="ml-1 text-xs font-normal text-ink-faint">{r.printed_dv}</s>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-ink-faint">{panel.basis}</p>
    </section>
  );
}
