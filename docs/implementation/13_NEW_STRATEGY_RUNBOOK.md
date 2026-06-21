# Naujos strategijos implementavimo instrukcija

Šios instrukcijos tikslas: nauja strategija nuo pirmo merge turi būti teisinga ir
pakankamai greita Optuna optimizacijai Railway aplinkoje. Greitas evaluator nėra
vėlesnė optimizacija. Jis yra privaloma strategijos implementacijos dalis.

## 1. Prieš rašant kodą apibrėžti našumo kontraktą

Strategijos užduotyje iš karto įrašyti:

- 100 Optuna trials;
- Railway `Optuna worker`, 3 vCPU, 3 GB RAM, 1 replika;
- 0 nepavykusių trials;
- mažiau nei 120 sekundžių `started_at -> completed_at` wall laiko;
- testuojamas didžiausias palaikomas M1 intervalas, ne trumpas demonstracinis
  intervalas;
- našumo matavimas atliekamas tik Railway, ne programuotojo kompiuteryje.

Rekomenduojamas vidinis tikslas yra ne 119 sekundžių, o ne daugiau kaip 90
sekundžių. Likusi atsarga reikalinga duomenų augimui ir Railway apkrovos svyravimui.

Jeigu UI profilis žada vienų metų arba maždaug 500 000 M1 žvakių intervalą,
acceptance testas privalo naudoti tokio pat dydžio datasetą. Mažesnio dataset'o
rezultatas tokio pažado neįrodo.

## 2. Parametrų modelis

Sukurti Pydantic modelį strategijos modulyje.

Kiekvienas Optuna optimizuojamas skaitinis parametras turi turėti abi ribas:

```python
period: int = Field(default=20, ge=2, le=300)
threshold: float = Field(default=1.5, gt=0, le=10)
```

Taisyklės:

- numatytoji reikšmė turi būti validi;
- ribos turi būti realistiškos, o ne dirbtinai didelės;
- `bool` ir `enum` laukai gali būti optimizuojami be skaitinių ribų;
- kiekvienas parametras turi turėti `description`, `unit` ir `impact` metaduomenis;
- `required_candles()` turi naudoti blogiausią parametrų kombinacijos lookback;
- negalima palikti parametrų, kurių Optuna gali parinkti į tarpusavyje nevalidžią
  kombinaciją.

Susietiems parametrams, pavyzdžiui `fast_period < slow_period`, geriausia modeliuoti
`fast_period` ir `slow_period_delta`. Jei API turi rodyti abu periodus, tą pačią
priklausomybę reikia pridėti į `sample_parameters()` faile
`apps/api/src/goldie_api/optimizations.py` ir parašyti testą, kuris daug kartų
generuoja kraštines reikšmes bei validuoja galutinį modelį.

## 3. Implementuoti du vykdymo kelius vienu metu

Strategija turi pateikti:

1. `evaluate()` - aiškią referencinę live/replay logiką.
2. `create_backtest_evaluator()` - paruoštą tikslų backtest kelią.
3. `create_fast_backtest_evaluator()` - Optuna skirtą inkrementinį kelią.

Optuna kviečia backtestą su `use_fast_strategy=True`. Jei
`create_fast_backtest_evaluator()` nėra, engine tyliai naudos lėtesnį
`create_backtest_evaluator()`. Todėl vien faktas, kad strategija veikia, neįrodo,
kad ji tinkama optimizacijai.

Fast evaluator reikalavimai:

- vienos žvakės apdorojimas turi būti O(1), o visas trial - O(N);
- indikatoriai atnaujinami inkrementiškai;
- rolling langams naudojamas riboto dydžio `deque` ir einamosios sumos;
- EMA, RSI, ATR, Bollinger ir range būsenos saugomos tarp `evaluate()` kvietimų;
- `Decimal` į `float` konvertuojamas vieną kartą žvakei, jei tai leidžia parity
  testai;
- naudojami `BacktestGuards`, kad fast ir referencinis keliai turėtų tas pačias
  spread bei session taisykles;
- fast kelias turi grąžinti tuos pačius `SignalType` ir reason code.

Fast evaluator viduje draudžiama kiekvienai žvakei:

- kopijuoti arba rūšiuoti visą candles sąrašą;
- kviesti `ema_series`, `rsi_series` ar kitą visą istoriją perskaičiuojančią
  funkciją;
- naudoti `list(window)` vien tam, kad perskaičiuotų rolling indikatorių;
- kurti `MarketContext` su visa istorija;
- atlikti DB užklausas ar rašymus.

## 4. Registracija

Viename pakeitime atlikti visus registravimo žingsnius:

1. Eksportuoti parametrų modelį ir strategiją iš
   `packages/trading-domain/src/goldie_domain/strategies/__init__.py`.
2. Importuoti ir užregistruoti strategijos egzempliorių
   `packages/trading-domain/src/goldie_domain/registry.py`.
3. Patikrinti, kad `/api/v1/strategies/catalog` grąžina strategiją, defaults ir
   visas parametrų ribas.
4. Patikrinti, kad web forma parametrus sukuria iš katalogo be hardcoded laukų.

## 5. Privalomi testai

Strategija negali būti laikoma baigta be šių testų:

### Funkciniai testai

- modelio defaults validūs;
- minimalios ir maksimalios ribos validuojamos;
- visos tarpusavio parametrų priklausomybės validuojamos;
- `required_candles()` teisingas;
- BUY, SELL ir NO_TRADE scenarijai;
- spread, session ir nepakankamų žvakių guard scenarijai;
- strategija yra registry ir API kataloge.

### Parity testai

`tests/test_backtest.py` strategiją pridėti į bendrą parametrizuotą sąrašą ir
palyginti pilną rezultatą:

```python
prepared = BacktestEngine().run(...)
fast = BacktestEngine().run(..., use_fast_strategy=True)
assert fast == prepared
```

Parity testas turi apimti:

- numatytuosius parametrus;
- minimalias ir maksimalias periodų reikšmes;
- crossover įjungtą ir išjungtą, jei taikoma;
- kylančią, krentančią, horizontalią ir triukšmingą kainų seką;
- kainų skales, panašias į EURUSD, JPY poras ir XAUUSD;
- bent vieną ilgesnę deterministinę žvakių seką.

Papildomas testas turi tiesiogiai patikrinti, kad strategija turi callable
`create_fast_backtest_evaluator`. Taip nebus galima netyčia išleisti strategijos,
kuri persijungia į lėtą fallback.

### Optuna search-space testai

- visi numatyti optimizuojami parametrai yra `build_search_space()` rezultate;
- 100 ar daugiau deterministinių sample kombinacijų validuojasi per strategijos
  Pydantic modelį;
- nė viena kombinacija nesukuria failed trial dėl parametrų tarpusavio ribų.

## 6. Lokali patikra

Lokaliai vykdomi tik correctness testai, ne našumo benchmarkas:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_strategy_registry.py tests\test_backtest.py tests\test_optimizations.py
.\.venv\Scripts\python.exe -m ruff check packages\trading-domain apps\api tests
```

Vietinis greitis negali būti naudojamas kaip 2 minučių reikalavimo įrodymas.

## 7. Railway acceptance testas

Po deployment į `just-friendship` production:

1. Patikrinti, kad `Optuna worker` naudoja naują commitą ir deployment yra
   `SUCCESS`.
2. Didžiausioje rinkoje paleisti naują strategiją su 100 trials ir visu
   palaikomu intervalu.
3. Patikrinti `successful_trials == 100`, `failed_trials == 0`.
4. Skaičiuoti wall laiką iš DB `completed_at - started_at`.
5. Reikalauti `wall_seconds < 120`.
6. Pakartoti kainų mastelio kraštinėse rinkose, bent JPY poroje ir XAUUSD, kai
   jose yra duomenų.
7. Jei strategijos sudėtingumas priklauso nuo rinkos savybių, testuoti visas
   production rinkas su duomenimis.

Benchmark užduotį galima įrašyti lokaliai, bet pats `execute_optimization()` ir
visi trials privalo veikti Railway `Optuna worker` procese.

## 8. Definition of Done

Nauja strategija baigta tik kai visi punktai yra teisingi:

- [ ] Parametrų modelis turi saugias Optuna ribas.
- [ ] Nė viena sugeneruota parametrų kombinacija nėra nevalidi.
- [ ] Implementuoti referencinis, prepared ir fast keliai.
- [ ] Fast evaluator vienai žvakei dirba O(1).
- [ ] Fast ir prepared rezultatai sutampa visuose parity testuose.
- [ ] Strategija registruota registry ir matoma API bei web UI.
- [ ] Visi correctness testai praeina.
- [ ] Railway benchmarkas baigia 100/100 trials be klaidų.
- [ ] Railway wall laikas mažesnis nei 120 sekundžių su sutartu maksimaliu
  datasetu.
- [ ] Benchmarkas nevykdytas vietinio kompiuterio resursais.

Jei bent vienas punktas neįvykdytas, strategija dar nėra paruošta production
Optuna optimizacijai.
