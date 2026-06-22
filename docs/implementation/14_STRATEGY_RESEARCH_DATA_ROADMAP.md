# Strategijos Tyrimų Duomenų Roadmap

## Paskirtis

Šis dokumentas aprašo, ką verta daryti po dabartinės Goldie V1 stadijos.
Jis atsako į tris klausimus:

1. ką toliau tobulinčiau strategijų tyrimo ir optimizavimo dalyje;
2. kokius papildomus duomenis rinkčiau, kad sprendimai būtų pagrįsti;
3. kokie papildomi projekto dokumentai turėtų atsirasti, kad tyrimo procesas būtų valdomas, atsekamas ir tinkamas LLM analizei.

Dokumentas remiasi šiais esamais šaltiniais:

- `README.md`
- `xauusd_trading_bot_3_men_planas_codex.md`
- `xauusd_trading_bot_funkciniai_reikalavimai.md`
- `xauusd_trading_bot_technologiju_architektura.md`
- `docs/implementation/11_OPTUNA_OPTIMIZATION_WORKFLOW.md`
- `docs/implementation/12_SHADOW_OUTCOME_EVALUATION.md`
- `apps/api/src/goldie_api/optimization_diagnostics.py`
- `apps/api/src/goldie_api/optimization_analysis.py`
- `apps/web/src/app/optimizations/[id]/page.tsx`

## Dabartinė V1 būsena

Goldie jau turi pakankamai stiprią pirmą tyrimų bazę:

- deterministinį M1 backtest variklį;
- Optuna optimizaciją `config.strategy.parameters` laukams;
- saugomas backtest trade eilutes ir summary;
- saugomus optimization trial ir run artefaktus;
- chronologinį search ir validation split optimizacijoje;
- fiksuoto grid validaciją `stop_loss_points` ir `take_profit_points`;
- run-level `research_quality_gates` su `PASS`, `WARN` ir `BLOCK` būsena;
- struktūruotą `data_profile`, `robustness`, `parameter_insights` ir `decision_context`;
- pilną optimization rezultatų eksportą ir kompaktišką LLM context eksportą;
- shadow outcome evaluation;
- immutable config snapshot ir `run_id`;
- bendrą trading-domain sluoksnį, kuris jau dabar jungia backtest, optimization ir shadow logiką.

Po V1.x kokybės vartų ši bazė jau atsako ne tik į klausimą:

```text
Kuris parametru rinkinys šiame run'e gavo geriausią score?
```

Ji taip pat pradeda atsakyti į klausimą:

```text
Ar šis optimization run pakankamai švarus ir robustiškas, kad jį verta svarstyti kaip kandidatą?
```

Tačiau ji dar tik iš dalies atsako į klausimus:

```text
Kodėl jis veikė?
Kur jis trapus?
Ar tai robustiška per kelis laiko langus ir rinkos režimus?
Ką reikia keisti toliau?
```

## Kas įgyvendinta V1.x fazėje

Šio roadmap P0 dalis jau perkelta į produktą:

- optimization terminal summary turi `research_quality_gates`;
- kiekvienas gate turi `id`, `status`, `severity`, `message` ir `evidence`;
- bendras statusas yra `PASS`, `WARN` arba `BLOCK`;
- gates remiasi validation trade sample, search-to-validation degradacija, data gaps, incomplete candles, failed trial rate, validation candidate coverage, drawdown ir consecutive losses;
- `/api/v1/optimizations/{id}` grąžina gates per `summary.research_quality_gates`;
- `/api/v1/optimizations/{id}/export` įtraukia gates į `analysis.research_quality_gates`;
- `/api/v1/optimizations/{id}/llm-context` įtraukia gates į `research_quality_gates` ir `run_context.research_quality_gates`;
- optimization detail UI turi `Research readiness` bloką;
- `BLOCK` būsenoje `Apply best as new config` reikalauja papildomo override patvirtinimo.

Tai nereiškia, kad sistema jau turi brandžią promotion policy.
Tai reiškia, kad V1 kandidatas nebegali būti vertinamas vien pagal `best_candidate.score`.

## Ką tobulinčiau po V1

### 1. Pereičiau nuo „best candidate“ prie robustumo vertinimo

Optimizacija neturi baigtis ties vienu laimėtoju.
Tolimesnė fazė turi vertinti:

- stabilumą tarp skirtingų laiko langų;
- stabilumą tarp skirtingų execution cost prielaidų;
- stabilumą kaimyniniuose parametrų taškuose;
- stabilumą skirtinguose rinkos režimuose;
- degradaciją tarp search ir validation rezultatų.

Pagrindinė taisyklė turėtų būti tokia:

```text
Įdomi strategija yra tik tada, kai panašūs parametrų regionai duoda panašų elgesį.
```

Konkretus EURUSD `bb_rsi_mean_reversion` LLM context pavyzdys parodė svarbų
anti-patterną: “geriausias” validation kandidatas gali turėti tik 1 sandorį,
neigiamą PnL, `TIMEOUT` exit ir labai užsmaugtus parametrus, pvz. 428 periodų
Bollinger, 6.25 deviation, 103 RSI period ir `require_touch_band = false`.
Tokio rezultato negalima traktuoti kaip “best settings”; tai yra signalas, kad
objective, search space arba pati strategijos hipotezė turi būti peržiūrėta.

### 2. Plėsčiau optimizacijos scope etapais, o ne vienu šuoliu

V1 pagrįstai optimizuoja tik `strategy.parameters`.
Toliau plėsčiau paiešką tokia seka:

1. palikti strategijos parametrus kaip pagrindinę paieškos erdvę;
2. daryti fiksuoto grid validaciją `stop_loss_points` ir `take_profit_points`;
3. tada pridėti nedidelį kontroliuojamą search trade-management laukams;
4. tik po to svarstyti `session`, `filters` ir režimo filtrų parametrus.

Prioritetiniai kandidatai:

- `theoretical_trade.stop_loss_points`
- `theoretical_trade.take_profit_points`
- `filters.max_spread_points`
- session langų parametrai
- režimo filtrų threshold'ai

Priežastis paprasta:
jei per anksti optimizuosime per daug dimensijų, bus sunku suprasti, ar signalo logika išvis turi pranašumą.

### 3. Įvesčiau walk-forward kaip pirmos klasės workflow

Funkciniuose reikalavimuose jau yra stipri nuoroda į:

- chronologinį train/validation/test;
- walk-forward analizę;
- anti-overfitting logiką.

Tai turi tapti realiu workflow, o ne tik gairėmis.

Būsimas optimization workflow turėtų palaikyti:

- kelis paeiliui einančius train/validation langus;
- pakartotinę optimizaciją kiekviename train segmente;
- forward testą kitame nematytame segmente;
- bendrą stabilumo ataskaitą per visus langus.

Be šito vienas optimization run vis dar per daug primena vieno periodo fitting.

### 4. Įvesčiau market regime analizę

Funkciniai reikalavimai aiškiai mini rinkos režimus.
Todėl optimization ir backtest rezultatai ilgainiui turėtų būti skaidomi bent pagal:

- trend
- range
- high volatility
- low liquidity
- abnormal arba news regime

Tai svarbu, nes strategija gali atrodyti gera bendrai, nors realiai veikia tik labai siaurame režime.

### 5. Sulyginčiau backtest, shadow ir būsimų execution režimų metrikas

Dabar turimos metrikos jau yra naudingos, bet kitas žingsnis turi būti parity tarp režimų.
Tai reiškia, kad tai pačiai strategijos šeimai turėtume lyginti:

- backtest teorinį rezultatą;
- shadow teorinį rezultatą;
- paper execution rezultatą;
- ateityje demo/live rezultatą.

Tikslas:
aiškiai matyti, kur atsiranda degradacija:

- signalo logikoje;
- execution modelyje;
- spread/slippage prielaidose;
- duomenų kokybėje;
- incidentuose ir operacinėje kokybėje.

### 6. Įvesčiau degradacijos ir incidentų kokybės vartus

Tyrimo sprendimai negali remtis tik PnL tipo rodikliais.
Sistema turėtų aiškiai kelti perspėjimus, kai:

- validation score stipriai krenta prieš search score;
- cost model sunaikina edge;
- vienas trade arba viena diena dominuoja bendrą rezultatą;
- best candidate turi per mažą trade sample, net jei jo score yra geriausias;
- data-gap uždarymų per daug;
- sample size per mažas išvadai;
- consecutive losses arba drawdown peržengia politikos ribas.

Šie signalai turi būti matomi ir UI, ir eksportuojamuose research artefaktuose.

## Kokius papildomus duomenis rinkčiau

## A. Signalų lygio tyrimo duomenys

Tai yra aukščiausio prioriteto trūkstamas sluoksnis LLM analizei.
Kiekvienam sugeneruotam signalui rinkčiau arba išlaikyčiau:

- signalo timestamp;
- symbol ir timeframe;
- strategijos pavadinimą ir parametrų snapshot;
- signalo kryptį;
- reason code;
- pilną indikatorių ir `inputs` snapshot;
- spread reikšmę sprendimo metu;
- session būseną;
- rinkos režimo žymę, jei ji apskaičiuota;
- ar signalas buvo priimtas, atmestas, praleistas ar pasibaigęs;
- atmetimo priežastį, jei sandoris nebuvo realizuotas.

Kodėl tai svarbu:
LLM tampa gerokai naudingesnis, kai mato ne tik outcome, bet ir patį sprendimo kontekstą bei atmetimo struktūrą.

## B. Trade gyvavimo ciklo duomenys

Dabartinis backtest trade modelis jau geras.
Jį plėsčiau arba veidrodiniu būdu pritaikyčiau visiems būsimiems execution režimams, kad būtų:

- planuota entry ir faktinė entry;
- planuotas SL/TP ir faktinis SL/TP;
- fill latency;
- slippage prieš modelį;
- komisijos ir spread kaštų išskaidymas;
- partial fill duomenys;
- exit trigger kategorija;
- MFE ir MAE santrauka;
- time-in-trade bucket.

Kodėl tai svarbu:
strategijos problema ir execution problema yra skirtingos problemos.
Šie duomenys leidžia jų nesumaišyti.

## C. Tyrimo sample kokybės duomenys

Kiekvienas backtest ar optimization artefaktas turėtų turėti:

- candle count;
- incomplete candle count;
- detected data-gap count;
- search, validation ir test date ranges;
- pasiskirstymą pagal mėnesį ir savaitės dieną;
- trade koncentraciją pagal dieną ir valandą;
- trade skaičių pagal regime;
- skipped signal skaičių pagal reason.

Kodėl tai svarbu:
sistema turi gebėti pasakyti, kada run yra statistiškai silpnas arba techniškai nešvarus.

## D. Parametrų elgsenos duomenys

Kiekvienam optimization run saugočiau:

- sampled parameter vector;
- score;
- pilną summary metrikų rinkinį;
- diagnostics santrauką;
- kaimyninių parametrų regionų elgseną, kai tai įmanoma;
- top-decile ir bottom-decile parametrų intervalus;
- numeric parametrų koreliaciją su score;
- search-to-validation degradaciją kiekvienai kandidatų šeimai.

Kodėl tai svarbu:
kitas strategijos sprendimas dažnai nėra „pasirink laimėtoją“, o „siaurink, platink arba mesk lauk šitą parametrą“.

## E. Regime ir aplinkos duomenys

Bręstant platformai rinkčiau:

- volatility bucket;
- ATR bucket;
- session label;
- day-of-week bucket;
- atstumą iki news-window;
- spread percentile bucket;
- liquidity arba stale-data žymes.

Kodėl tai svarbu:
šie atributai reikalingi regime-aware filtravimui, challenger strategijoms ir LLM modelių pattern discovery.

## F. Operacinio patikimumo duomenys

Strategijos sprendimai turi apimti ne tik outcome, bet ir sistemos kokybę.
Todėl rinkčiau:

- worker restart'us;
- optimization failure reason'us;
- collector heartbeat gap'us;
- ingestion lag;
- incident count pagal klasę;
- reconciliation mismatch'us;
- aplinkos metadata kiekvienam run.

Kodėl tai svarbu:
jei strategija atrodo blogai dėl sistemos kokybės, parametrų keitimas būtų klaidingas atsakas.

## Duomenų rinkimo prioritetai

### P0: jau įgyvendinta arba stabilizuota V1.x fazėje

- validation prieš search degradacija
- praplėstos trial metrics
- data quality profile kiekvienam run
- kompaktiškas LLM-ready export
- run-level `research_quality_gates`
- `PASS`, `WARN`, `BLOCK` research readiness būsena UI
- full optimization export su `analysis.research_quality_gates`

### P0: dar likę artimiausiam V1.x užbaigimui

- griežtesnis minimalus trade-sample evidence target objective funkcijoje;
- signal context snapshot
- accepted, rejected ir expired reason counts
- aiškesnis signal rejection ir skipped signal breakdown backtest/shadow artefaktuose
- dokumentuotas canonical research data contract
- dokumentuotas quality gate threshold'ų kontraktas

### P1: kitas research ciklas

- walk-forward window artefaktai
- spread ir slippage stress scenarijai
- regime labels
- concentration analysis pagal laiko bucket
- sample-confidence ir stabilumo indikatoriai

### P2: paper/demo execution ciklas

- actual-versus-modeled fill metrics
- latency ir partial-fill detalės
- incident-aware execution diagnostika
- reconciliation delta

### P3: pažangesnis research sluoksnis

- champion/challenger palyginimo paketai
- automatinis degradacijos aptikimas
- regime-specific recommendation santraukos
- flight-recorder tipo bundle anomalijoms

## Kokie papildomi dokumentai turėtų atsirasti

Projektas jau turi stiprius architektūros ir workflow dokumentus.
Toliau pridėčiau šiuos dokumentus.

### 1. Strategy Research Data Contract

Siūlomas kelias:

`docs/implementation/15_STRATEGY_RESEARCH_DATA_CONTRACT.md`

Paskirtis:

- apibrėžti canonical research objektus;
- nustatyti, kurie laukai yra privalomi signal, trade, backtest, optimization ir shadow artefaktams;
- aprašyti stabilius JSON export kontraktus;
- atskirti raw, derived ir diagnostic laukus.

Šis dokumentas turėtų tapti pagrindiniu tiesos šaltiniu analytics API ir LLM exportams.
Po V1.x quality gates implementacijos jis turėtų aprašyti jau atsiradusias sekcijas:

- `summary.data_profile`
- `summary.robustness`
- `summary.parameter_insights`
- `summary.research_quality_gates`
- optimization full export `analysis`
- optimization LLM context payload

### 2. Research Quality Gates

Siūlomas kelias:

`docs/implementation/16_RESEARCH_QUALITY_GATES.md`

Paskirtis:

- aprašyti minimalius sample reikalavimus;
- apibrėžti robustumo pass/fail slenksčius;
- aprašyti, kada optimization rezultatai gali būti keliami į shadow arba paper;
- apibrėžti, kas laikoma overfit elgsena;
- apibrėžti stop sąlygas silpniems run'ams.

Šis dokumentas turėtų tiesiogiai sietis su jau esančiais `BACKTEST -> SHADOW -> DEMO` vartais funkciniuose reikalavimuose.
V1.x jau turi pirmą implementuotą versiją, todėl dokumentas turi nebe tik siūlyti idėją, bet formalizuoti:

- dabartinius threshold'us;
- `PASS`, `WARN`, `BLOCK` semantiką;
- kada `BLOCK` yra tik UI override perspėjimas;
- kada `BLOCK` ateityje turėtų realiai stabdyti promotion workflow;
- kaip gates turi būti interpretuojami LLM analizėje.

### 3. Walk-Forward Orchestration Spec

Siūlomas kelias:

`docs/implementation/17_WALK_FORWARD_OPTIMIZATION.md`

Paskirtis:

- aprašyti windowing taisykles;
- aprašyti train/validation/test split elgseną;
- apibrėžti agreguotą scoring logiką;
- apibrėžti reikiamus output ir report;
- nuspręsti, kaip fixed config validation sąveikauja su walk-forward run'ais.

Tai yra vienas svarbiausių trūkstamų workflow po dabartinės Optuna V1 fazės.

### 4. Regime Classification Spec

Siūlomas kelias:

`docs/implementation/18_MARKET_REGIME_CLASSIFICATION.md`

Paskirtis:

- apibrėžti palaikomus rinkos režimus;
- aprašyti classification logiką ir threshold'us;
- apibrėžti, kurios metrikos privalo būti skaidomos pagal režimą;
- aprašyti, kaip regime label saugomi ir atvaizduojami.

Tai apsaugotų regime analytics nuo ad hoc sprendimų kiekvienai strategijai atskirai.

### 5. Strategy Promotion Policy

Siūlomas kelias:

`docs/implementation/19_STRATEGY_PROMOTION_POLICY.md`

Paskirtis:

- aprašyti, kada kandidatas gali būti keliams iš optimization į shadow;
- aprašyti, kada shadow gali keliauti į paper arba demo;
- nustatyti freeze, rollback ir approval taisykles;
- aiškiai nurodyti, kokių įrodymų reikia prieš kitą fazę.

Tai mažina emocinius arba per ankstyvus parametrų pakeitimus.

### 6. LLM Research Context Spec

Siūlomas kelias:

`docs/implementation/20_LLM_RESEARCH_CONTEXT_SPEC.md`

Paskirtis:

- aprašyti compact ir full export skirtumą;
- apibrėžti maksimalų payload dydį;
- nustatyti redaction ir summarization taisykles;
- aprašyti, kurias sekcijas LLM visada turi gauti;
- nustatyti, kokios išvados negali būti daromos iš per mažo sample.

Tai svarbu, jei LLM-driven research tampa nuolatine workflow dalimi, o ne vienkartiniu eksportu.

## Ko vengčiau

Kitoje fazėje klaida būtų:

- optimizuoti per daug laukų vienu metu;
- pasitikėti vienu laimėjusiu run be stabilumo įrodymų;
- maišyti techninius incidentus su strategijos išvadomis;
- remtis tik total PnL ar vienu score;
- eiti į live prieš įrodant shadow ir paper paritetą;
- leisti UI laukams netyčia tapti pagrindiniu research contract;
- duoti LLM eksportus be dokumentuotos laukų semantikos.

## Rekomenduojama seka po dabartinės V1.x

1. Formalizuoti research data contract signalams, trial, run, export ir LLM context payload'ams.
2. Formalizuoti V1.x `research_quality_gates` threshold'us dokumente `16_RESEARCH_QUALITY_GATES.md`.
3. Sustiprinti signal-context ir rejection-reason saugojimą.
4. Įgyvendinti walk-forward orchestration.
5. Įvesti regime labeling ir regime-based reporting.
6. Įvesti paper/demo execution parity metrikas.
7. Įvesti promotion policy ir incident-aware operational gates.

## Galutinė pozicija po V1.x

Dabartinė V1.x jau pakanka:

- deterministiniam backtest research;
- pirmajam strategy parameter search ciklui;
- pakankamam artefaktų kaupimui kandidatų palyginimui;
- pirmajam praktiškai naudingam LLM context export.
- pirmajam run-level research readiness vertinimui;
- aiškiam perspėjimui, kai optimization rezultatas yra per silpnas promotion sprendimui;
- žmogui ir LLM tinkamam `PASS`, `WARN`, `BLOCK` kontekstui.

Dabartinė V1.x dar nepakanka:

- stipriems teiginiams apie tikrą edge;
- brandžiam anti-overfitting sprendimų priėmimui;
- paper, demo ar live promotion sprendimams be papildomų vartų;
- aukšto pasitikėjimo regime-aware strategijos tobulinimui.

Todėl po V1.x prioritetas turėtų būti ne agresyvesnė optimizacija, o:

- research data contract formalizavimas;
- quality gate threshold'ų dokumentavimas ir kalibravimas;
- robustumo ir walk-forward įrodymai;
- signal-level kontekstas ir atmetimo analizė;
- execution-mode parity;
- aiškūs dokumentai, kurie saugo nuo per silpnų duomenų perinterpretavimo.
