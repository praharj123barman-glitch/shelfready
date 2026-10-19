# Mutation eval (code checks)

Each row edits the real Esko sample (PDF text via redaction, or one content-sheet cell) and runs the full
pipeline: PDF extraction, then every check. A detection counts only if the expected check newly fails;
a repair counts only if the expected finding goes away. Any other check that gets worse is a false alarm.

**Detected:** 16/16  ·  **Repairs recognised:** 7/7  ·  **False alarms:** 0 across 23 mutations

| ID | Kind | Edit | Expected check (before -> after) | OK | False alarms |
|---|---|---|---|---|---|
| D01 | detect | Storage text reworded ('cool' to 'warm') | text_storage_instructions: pass -> definite | yes | 0 |
| D02 | detect | Marketing copy shortened | text_marketing_copy: pass -> definite | yes | 0 |
| D03 | detect | Brazil nuts dropped from the allergen statement | text_allergen_information: pass -> definite | yes | 0 |
| D04 | detect | Saturated fat raised so fats exceed total fat | subtotals: pass -> definite | yes | 0 |
| D05 | detect | Trans fat raised so fats exceed total fat | subtotals: pass -> definite | yes | 0 |
| D06 | detect | Total sugars larger than total carbohydrate | subtotals: pass -> definite | yes | 0 |
| D07 | detect | %DV footnote removed | nf_present: pass -> likely | yes | 0 |
| D08 | detect | Ingredient listed twice | ingredient_structure: pass -> definite | yes | 0 |
| D09 | detect | Declared percentages out of descending order | ingredient_structure: pass -> definite | yes | 0 |
| D10 | detect | Net weight declaration deleted | net_quantity: - -> definite | yes | 0 |
| D11 | detect | Unapproved 'GLUTEN FREE' claim added to the front | claims_approved: likely -> likely | yes | 0 |
| D12 | detect | Statement of identity removed from the front | identity: pass -> definite | yes | 0 |
| D13 | detect | Sheet UPC changed (barcode no longer matches) | barcode: pass -> definite | yes | 0 |
| D14 | detect | Sheet net weight changed to 500g | net_quantity_sheet: pass -> definite | yes | 0 |
| D15 | detect | Sheet storage text changed | text_storage_instructions: pass -> definite | yes | 0 |
| D16 | detect | Copy pushed across the front/left fold | folds: definite -> definite | yes | 0 |
| R01 | repair | Net weight added to the front in oz and g at legal size | net_quantity_pdp: definite -> gone, net_quantity_units: definite -> gone, net_qty_height: definite -> pass | yes | 0 |
| R02 | repair | Manufacturer address added | manufacturer: definite -> pass | yes | 0 |
| R03 | repair | Serving size given household and metric units | serving_size: definite -> pass, servings_math: likely -> pass | yes | 0 |
| R04 | repair | Calories corrected to match the macronutrients | calories_atwater: definite -> pass | yes | 0 |
| R05 | repair | Calories, sodium and potassium rounded the FDA way | rounding: definite -> pass | yes | 0 |
| R06 | repair | Duplicate sunflower seeds removed from the sheet | sheet_ingredient_duplicates: review -> gone | yes | 0 |
| R07 | repair | Sheet carbohydrate corrected to the artwork value | sheet_sugars_gt_carbs: review -> gone | yes | 0 |

No false alarms.

## Bugs this eval found in the checker (all fixed)

The first run scored 12/16 detected, 6/7 repairs and 1 false alarm. Reading every miss found five real
checker bugs, not just eval noise:

1. Servings math read the first number of '3/4 cup (60g)' (3) instead of the grams (60).
2. With '480g' gone, the net-weight check picked up '3.8g' from the EU fat icon as the pack weight.
   Nutrient amounts are now excluded from net quantity detection.
3. Face names came only from dieline guide labels; deleting one ('Back panel') made the back face
   disappear. Unlabelled faces are now named from geometry (wide column with the largest type is the front).
4. The net quantity height check measured the first quantity found, not the one on the front panel.
5. A legal 'NET WT 16.9 OZ (480g)' declaration was flagged as unapproved marketing copy.

AI checks (rulebook reasoning, marks) are not part of this run; they are evaluated by their evidence
verification, see README.
