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

// Padaryti Optimatizacijų profilį, kas tas yra fill ? Ar pas mus jis yra ..

Perfect-fill (naudoti tik palyginimui)
{
"FromTo":"2023-01-01:2025-01-01",
"Trials":100,
"Initial capital":10000,
"makerFee":0.0,
"takerFee":0.0,
"takerSlippage":0.0,
"smallSlippage":0.0,
"mediumImpact":0.0,
"modelsqrtLimit":1.0,
"fill":"perfect",
"timeout_s":1,
"Min_qty_check":0.0,
"check":false
}

Realistic (baseline for optimizer)
{
"FromTo":"2023-01-01:2025-01-01",
"Trials":500,
"Initial capital":10000,
"makerFee":0.0002,
"takerFee":0.0006,
"takerSlippage":0.0005,
"smallSlippage":0.0002,
"mediumImpact":0.001,
"modelsqrtLimit":1.0,
"fill":"simulated",
"timeout_s":5,
"Min_qty_check":0.01,
"check":true
}

Stress (conservative / worst-case to see robustness)
{
"FromTo":"2023-01-01:2025-01-01",
"Trials":500,
"Initial capital":10000,
"makerFee":0.0005,
"takerFee":0.0010,
"takerSlippage":0.0015,
"smallSlippage":0.0008,
"mediumImpact":0.003,
"modelsqrtLimit":0.7,
"fill":"simulated",
"timeout_s":10,
"Min_qty_check":0.02,
"check":true
}