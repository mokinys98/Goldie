# Algoritmai, suderinami su esamais "combos" ir rekomenduotas kandidatas

Šiame dokumente surašyti algoritmai, kurie yra suderinami su esama projekto struktūra (naudojant jau egzistuojančius indikatorius: EMA, RSI, ATR, Bollinger Bands), bei pateikta mano prioritetinė rekomendacija.

## Algorithms that fit the current combos (compatible with existing code)

1) Bollinger Bands + RSI mean-reversion (BB + RSI)
- Kas vyksta: įeinama, kai kaina paliečia arba išeina už Bollinger juostų ribų, o RSI rodo overbought/oversold.
- Kodėl tinka: `bollinger_bands` ir `rsi` jau yra `packages/trading-domain/src/goldie_domain/indicators.py`.
- Privalumai: gerai veikia range-bound rinkoje; paprasta testuoti ir parametrizuoti.
- Trūkumai: blogas veikimas stipriame trende.
- Pagrindiniai parametrai: bollinger_period, deviations, rsi_period, rsi thresholds, atr_stop_multiplier.

2) EMA Momentum Breakout (multi-EMA + momentum)
- Kas vyksta: breakout kai greitos EMA > vidutinės > lėtos ir momentum teigiamas.
- Kodėl tinka: `ema_series`, `momentum` jau egzistuoja.
- Privalumai: pagauna trendus; paprastas įgyvendinimas kaip `ema_rsi` variacija.
- Trūkumai: reikalingi filtrai (ATR/min_trend_points) užkirsti kelią klaidingiems breakoutams.

3) EMA + ATR volatility filter (trend-following su dinaminiais SL)
- Kas vyksta: išlaikomas EMA crossover kaip įėjimas, bet ATR naudojamas filtrui ir dinaminėms stop-loss reikšmėms.
- Kodėl tinka: `atr` egzistuoja ir leidžia pritaikyti SL pagal rinkos volatiliumą.
- Privalumai: adaptuojasi į skirtingą volatilumą; mažiau noise.

4) Bollinger Breakout + momentum confirmation
- Kas vyksta: prekiaujama, kai išauga volatilumas ir kaina įveikia Bollinger juostas kartu su momentum/ATR augimu.
- Kodėl tinka: puikiai naudoja esamus indikatorius.

5) Mean reversion with EMA trend normalization (BB + EMA + RSI)
- Kas vyksta: leidžiama mean-reversion tik, kai EMA rodo neutralią arba silpną tendenciją; mažina klaidingus signalus prieš trendą.
- Kodėl tinka: jungia `ema_rsi` tipo logiką su BB+RSI.

6) Range-break scalper (short EMA + RSI)
- Kas vyksta: trumpalaikis skalpavimas M1 laiko intervale su labai trumpais EMA ir griežtu slippage/spread filtru.
- Kodėl tinka: pagrindiniai building blocks (EMA, RSI, spread guards) jau yra.

---

## My recommended profitable candidate (one to prioritize)

Rekomendacija: Bollinger Bands + RSI mean-reversion su ATR-dinamikos stopu (BB + RSI + ATR stop).

### Kodėl ši kombinacija
- Statistiškai daug trumpalaikių M1 EURUSD judesių grįžta prie vidurkio; BB identifikuoja reikšmingas divergencijas, o RSI padeda išvengti signalo per ankstyvos įėjimo, kai judėjimas turi momentum.
- ATR stop leidžia adaptuoti SL prie dabartinės volatilumos.
- Visos reikalingos funkcijos jau yra `packages/trading-domain/src/goldie_domain/indicators.py` (bollinger_bands, rsi, atr), todėl implementacija bus žema rizika.

### Pagrindiniai taisyklės bruožai (aukštas lygis)
- Entry (BUY): kaina uždaro žemiau apatinės Bollinger ribos (arba palietė) + RSI <= buy_rsi_max (pvz. 45) + (nebent EMA rodo stiprų down-trend; opcionalus EMA trend filter).
- Entry (SELL): kaina uždaro virš aukštos Bollinger ribos + RSI >= sell_rsi_min (pvz. 55).
- Stop-loss: ATR * atr_stop_multiplier (konvertuoti į punktus pagal `point`), arba fiksuotas SL jeigu pageidaujama.
- Take-profit: statinis TP arba RR patern (pvz. 1:1.5 TP/SL) arba dinaminis TP pagal ATR.
- Filtrai: max_spread_points, stale_after_seconds, session time window (kaip jūsų esamuose eksportuose).

### Parametrai siūlomi pagal rizikos profilį

Aggressive
- bollinger_period: 14
- bollinger_deviations: 1.8
- rsi_period: 10
- buy_rsi_max: 50
- sell_rsi_min: 50
- atr_period: 10
- atr_stop_multiplier: 1.2
- require_touch_band: true
- risk_per_trade_pct: 0.4
- trumpalaikis TP/SL kaip jūsų `aggressive` export

Balanced
- bollinger_period: 20
- bollinger_deviations: 2
- rsi_period: 14
- buy_rsi_max: 45
- sell_rsi_min: 55
- atr_period: 14
- atr_stop_multiplier: 1.5
- risk_per_trade_pct: 0.28

Conservative
- bollinger_period: 20
- bollinger_deviations: 2.5
- rsi_period: 18
- buy_rsi_max: 40
- sell_rsi_min: 60
- atr_period: 20
- atr_stop_multiplier: 2.0
- risk_per_trade_pct: 0.15

### Įdiegimo instrukcijos (kur pridėti kodą)
1) Sukurti strategijos modulį:
- failas: `packages/trading-domain/src/goldie_domain/strategies/bb_rsi_mean_reversion.py`
- struktūra: atkartoti `EmaRsiStrategy` stilių (Pydantic parametrų modelis, `required_candles`, `evaluate`, `create_backtest_evaluator`)
- naudoti: `from ..indicators import bollinger_bands, rsi, atr` ir `common_guard`, `trade_prices`, `BacktestGuards` kaip `ema_rsi.py`.

2) Pridėti vienetinius testus:
- panašiai kaip `tests/test_strategy_registry.py` pridėti testą, kuris patikrina BUY/SELL/NO_TRADE elgseną su supaprastintais kainų aibėmis.

3) Sukurti eksportus JSON formatu (kaip jau turite `exports/strategies/...`) kiekvienam rizikos profiliui.

4) Backtest:
- naudokite esamą backtest harness (tests ar backtest runner). Pavyzdys (PowerShell):

```powershell
# įdirbkite virtualenv jei reikia, tada:
pytest tests/test_backtest.py -k bb_rsi_mean_reversion -q
```

(arba paleiskite konkrečius backtest scenarijus, jei turite backtest runner scriptą.)

5) Shadow/Paper run
- Pritaikykite naują konfigūraciją UI ar JSON exportu, paleiskite shadow režimą ir rinkite statistiką prieš live.

### Papildomi patarimai ir tolesni žingsniai
- Pridėkite opcionalų EMA trend filter (pvz. reikalauti, kad trend_points tarp greitos ir lėtos EMA būtų mažas) jeigu norite mažinti trades prieš stipresnį trendą.
- Surinkite backtest rezultatus per skirtingus rinkos režimus (ramp up, news, calm) ir vertinkite k: Sharpe, max drawdown, avg trade, winrate.
- Startuokite su `balanced` profiliu shadow režime savaitę ar dvi ir tik tada scale-in į agresyvų profilį.

---

Jeigu norite, galiu dabar sukurti:
- `packages/trading-domain/src/goldie_domain/strategies/bb_rsi_mean_reversion.py` su pilnu implementation ir pridėti vienetinius testus; arba
- Pridėti agresyvią ir konservatyvią JSON konfigūraciją prie `exports/strategies/`.

Pasakykite, kurią opciją norite — aš galiu ją įgyvendinti ir paleisti atitinkamą testų rinkinį.