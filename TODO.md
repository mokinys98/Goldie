Trumpas kontrolinis sąrašas (veiksmai):

1. Surink ir patikrink duomenų kokybę.
2. Apibrėžk trading assumptions (slippage, fill rules, komisijos).
3. Implementuok greitą baseline backtester.
4. Paleisk sanity check su keliomis strategijomis/periodais.
5. Jei baseline OK → pridėk execution realism ir parametrų paiešką.
6. Atlik walk‑forward / OOS ir koreguok modelius pagal overfitting indikatorius.
7. Automatinis logging, versijavimas, reproducibility.
8. Paruošk santrauką su aiškiais KPI ir veiksmų planu gyvai prekybai.
Praktiniai patarimai dėl laiko taupymo:

Start small: pirmasis sprintas — tik baseline ir duomenų patikra.
Profiling + paralelizacija: identifikuok lėtus kaštus, palygink lokalų vs cloud.
Panaudok sanity‑samples: vietoj pilnos istorijos testuok su reprezentatyviais segmentais.
Automatizuok eksperimentus: CI‑style runs, rezultatai į DB/CSV su metaduomenimis.