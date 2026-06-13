# XAU/USD Trading Bot – 3 mėn. bandomasis planas Codex'ui

## 1. Projekto paskirtis

Sukurti bandomąjį XAU/USD trading botą, kuris per 3 mėnesius padėtų įvertinti, ar automatinė aukso prekybos strategija turi praktinį pagrindą.

Svarbu: projekto tikslas nėra greitas pelnas. Pagrindinis tikslas – sukurti kontroliuojamą, mažos rizikos testavimo sistemą, kuri:

- renka rinkos duomenis;
- generuoja signalus;
- vykdo paper trading / demo trading;
- testuoja strategiją istoriniuose duomenyse;
- riboja nuostolius;
- saugo kiekvieno veiksmo log'ą;
- leidžia priimti sprendimą pagal statistiką, o ne emociją.

## 2. Rizikos lygio tikslas

Siekiamas rizikos lygis: **3/7**.

Tai reiškia:

- nenaudoti agresyvaus 15 sekundžių scalping pradžioje;
- pradėti nuo 1–5 min. sandorių;
- naudoti demo arba cent account;
- nerizikuoti daugiau kaip 0,25–0,5 % sąskaitos vienam sandoriui;
- turėti dienos ir savaitės nuostolio limitus;
- kiekvienas sandoris privalo turėti stop-loss;
- draudžiama naudoti martingale, grid be stop-loss arba lotų dvigubinimą po nuostolio.

## 3. Instrumentas

Pradinis instrumentas:

```text
XAU/USD
```

Galimas prekybos būdas:

```text
Provider-neutral paper prekyba pagal OANDA XAU/USD kainas
```

Rekomenduojama pradėti nuo:

```text
Demo account -> Cent account -> Small real account
```

## 4. Projekto trukmė

Bandomasis laikotarpis:

```text
3 mėnesiai / 12 savaičių
```

Bendras tikslas po 3 mėnesių:

```text
Atsakyti, ar botas turi bent minimalų matematinį pranašumą, ar tik atsitiktinai atidarinėja sandorius.
```

---

# 5. Etapai

## 5.1. 1–2 savaitė – taisyklių ir strategijos aprašymas

### Tikslas

Sukurti aiškų strategijos ir rizikos taisyklių aprašą, kurį būtų galima programuoti.

### Botas šiuo etapu dar neturi prekiauti.

### Reikia aprašyti:

- kada botas gali prekiauti;
- kada botas negali prekiauti;
- kokia strategija naudojama;
- kada generuojamas BUY signalas;
- kada generuojamas SELL signalas;
- kur dedamas stop-loss;
- kur dedamas take-profit;
- koks maksimalus sandorio laikas;
- kokia rizika vienam sandoriui;
- koks maksimalus dienos nuostolis;
- kada botas turi automatiškai sustoti.

### Pradiniai nustatymai

| Parametras | Reikšmė |
|---|---|
| Instrumentas | XAU/USD |
| Laiko intervalas | M1 / M5 |
| Sandorio trukmė | 1–5 min. |
| Rizika per sandorį | 0,25–0,5 % |
| Maks. dienos nuostolis | 1–2 % |
| Maks. sandorių per dieną | 5–10 |
| Vienu metu atidarytų pozicijų skaičius | 1 |
| Martingale | Draudžiama |
| Grid be SL | Draudžiama |
| Prekyba per naujienas | Draudžiama |

### Acceptance criteria

- Yra strategijos taisyklių failas.
- Yra rizikos taisyklių failas.
- Visi parametrai gali būti keičiami per konfigūraciją.
- Nėra hardcoded reikšmių strategijos kode.

---

## 5.2. 3–4 savaitė – duomenų rinkimo ir signalų registravimo botas

### Tikslas

Botas dar neatidaro sandorių. Jis tik stebi rinką, generuoja teorinius signalus ir viską įrašo į log'ą.

### Funkcijos

Botas turi rinkti:

- datą ir laiką;
- XAU/USD bid kainą;
- XAU/USD ask kainą;
- spread'ą;
- žvakių duomenis;
- signalo tipą;
- teorinę entry kainą;
- teorinį stop-loss;
- teorinį take-profit;
- teorinį sandorio rezultatą;
- priežastį, kodėl signalas buvo arba nebuvo priimtas.

### Pavyzdinė log'o struktūra

| Field | Type | Description |
|---|---|---|
| timestamp | datetime | Signalo laikas |
| symbol | string | XAU/USD |
| bid | float | Bid kaina |
| ask | float | Ask kaina |
| spread | float | Spread dydis |
| signal | string | BUY / SELL / NONE |
| entry_price | float | Teorinė įėjimo kaina |
| stop_loss | float | SL |
| take_profit | float | TP |
| result | string | WIN / LOSS / TIMEOUT / SKIPPED |
| reason | string | Signalo priežastis arba atmetimo priežastis |

### Minimalus tikslas

Surinkti:

```text
100–200 teorinių signalų
```

### Acceptance criteria

- Botas gali veikti paper trading režimu.
- Nėra realių pavedimų.
- Kiekvienas signalas įrašomas į CSV arba SQLite duomenų bazę.
- Galima atskirti priimtus ir atmestus signalus.
- Galima matyti, kiek signalų per dieną sugeneruojama.

---

## 5.3. 5–6 savaitė – backtesting modulis

### Tikslas

Patikrinti strategiją istoriniuose XAU/USD duomenyse.

### Backtestas turi įskaičiuoti:

- spread'ą;
- komisiją, jeigu taikoma;
- slippage prielaidą;
- stop-loss;
- take-profit;
- maksimalų sandorio laiką;
- dienos nuostolio limitą;
- maksimalų sandorių kiekį per dieną.

### Reikalingi rodikliai

| Rodiklis | Tikslas |
|---|---|
| Total trades | Bendras sandorių kiekis |
| Win rate | Laimėtų sandorių procentas |
| Average win | Vidutinis laimėjimas |
| Average loss | Vidutinis pralaimėjimas |
| Profit factor | Pageidautina > 1.1–1.2 testuose |
| Max drawdown | Kontroliuojamas |
| Consecutive losses | Kiek nuostolių iš eilės |
| Spread impact | Kiek pelno suvalgo spread'as |
| Net result | Rezultatas po kaštų |

### Svarbi taisyklė

Nereikia ieškoti vieno „stebuklingo“ parametro.

Geras ženklas:

```text
Keli panašūs nustatymai duoda panašų, stabilų rezultatą.
```

Blogas ženklas:

```text
Vienas nustatymas rodo didelį pelną, bet visi kiti nustatymai yra minusiniai.
```

### Acceptance criteria

- Yra backtest funkcija.
- Backtest galima paleisti su skirtingais parametrais.
- Rezultatai eksportuojami į CSV / JSON.
- Rodomas bent minimalus performance report.
- Backtest įskaičiuoja spread'ą ir slippage.

---

## 5.4. 7–8 savaitė – demo forward testas

### Tikslas

Botas turi veikti gyvoje rinkoje demo sąskaitoje.

### Botas turi atlikti šiuos veiksmus:

1. Patikrinti, ar dabar leidžiamas prekybos laikas.
2. Patikrinti, ar nėra svarbių naujienų lango.
3. Patikrinti, ar spread'as ne per didelis.
4. Gauti XAU/USD kainą.
5. Apskaičiuoti strategijos signalą.
6. Jeigu signalo nėra – laukti.
7. Jeigu signalas yra – apskaičiuoti lotą pagal riziką.
8. Atidaryti demo sandorį.
9. Uždėti stop-loss ir take-profit.
10. Stebėti sandorį.
11. Uždaryti pagal TP / SL / laiko limitą.
12. Įrašyti rezultatą į log'ą.
13. Pasiekus dienos nuostolio limitą – išjungti prekybą.

### Kill switch taisyklės

Botas privalo sustoti, jeigu:

- pasiektas dienos nuostolio limitas;
- pasiektas savaitės nuostolio limitas;
- yra 3 pralaimėjimai iš eilės;
- spread'as viršija leidžiamą ribą;
- nepavyksta uždėti stop-loss;
- nutrūksta ryšys su brokeriu;
- gaunama netikėta brokerio klaida.

### Acceptance criteria

- Botas gali veikti demo režimu.
- Botas realiai atidaro ir uždaro demo sandorius.
- Kiekvienas sandoris turi SL ir TP.
- Jeigu SL neuždedamas, botas neatidaro arba nedelsiant uždaro sandorį.
- Veikia dienos nuostolio limitas.
- Veikia prekybos sustabdymas po klaidos.

---

## 5.5. 9–10 savaitė – mažas realus testas

### Tikslas

Testuoti botą su mažu kapitalu arba cent account.

### Rekomenduojami limitai su 50 EUR sąskaita

| Parametras | Reikšmė |
|---|---|
| Rizika per trade | 0,25–0,5 % |
| Rizika pinigais | apie 0,13–0,25 EUR |
| Max dienos nuostolis | apie 1 EUR |
| Max savaitės nuostolis | 3–5 EUR |
| Max bendras nuostolis testui | 10 % sąskaitos |
| Max sandoriai per dieną | 5 |
| Vienu metu atidarytos pozicijos | 1 |

### Pagrindinė taisyklė

Jeigu sąskaita nuo 50 EUR nukrenta iki 45 EUR:

```text
Eksperimentas stabdomas ir analizuojamas.
```

### Acceptance criteria

- Botas veikia realioje arba cent sąskaitoje su mažiausiu įmanomu lotu.
- Botas neviršija nustatytų nuostolio limitų.
- Realūs rezultatai lyginami su demo rezultatais.
- Fiksuojami execution skirtumai: spread, slippage, rejected orders.

---

## 5.6. 11–12 savaitė – analizė ir sprendimas

### Tikslas

Įvertinti, ar projektą verta tęsti.

### Reikia atsakyti į klausimus:

1. Ar botas laikėsi taisyklių?
2. Ar buvo techninių klaidų?
3. Ar kiekvienas sandoris turėjo stop-loss?
4. Ar realūs rezultatai panašūs į demo / backtest rezultatus?
5. Ar strategija neveikė tik dėl vienos atsitiktinai geros dienos?
6. Ar drawdown yra priimtinas?
7. Ar spread'as ir slippage nesuvalgė strategijos pranašumo?
8. Ar surinkta pakankamai sandorių?
9. Ar verta tęsti?
10. Ar reikia keisti strategiją?

### Projekto sėkmės kriterijai

| Tikslas | Reikšmė |
|---|---|
| Botas veikia be kritinių klaidų | Taip |
| Kiekvienas sandoris turi SL | 100 % |
| Martingale nenaudojamas | 100 % |
| Yra pilnas log'as | Taip |
| Demo sandorių kiekis | 100–200+ |
| Realus nuostolis | Ne daugiau 10 % |
| Strategija | Bent nenuostolinga po kaštų |
| Vartotojas supranta įėjimo priežastis | Taip |

---

# 6. Aukšto lygio boto veikimo schema

```text
START
↓
Load config
↓
Connect to broker / data source
↓
Check trading session
↓
Check news filter
↓
Check daily and weekly risk limits
↓
Fetch XAU/USD bid/ask price
↓
Calculate spread
↓
If spread too high -> skip
↓
Fetch candle / tick data
↓
Calculate indicators / strategy signal
↓
If no signal -> wait
↓
If signal exists -> calculate position size
↓
Validate risk
↓
Place order
↓
Attach stop-loss and take-profit
↓
Monitor open position
↓
Close by TP / SL / timeout / kill switch
↓
Log trade result
↓
Update daily statistics
↓
If limits breached -> stop trading
↓
Repeat
```

---

# 7. Siūloma projekto failų struktūra

```text
xauusd-trading-bot/
│
├── README.md
├── config/
│   ├── config.example.yaml
│   ├── strategy.yaml
│   └── risk.yaml
│
├── data/
│   ├── raw/
│   ├── processed/
│   └── backtest_results/
│
├── logs/
│   ├── signals.csv
│   ├── trades.csv
│   └── errors.log
│
├── src/
│   ├── main.py
│   ├── broker/
│   │   ├── mt5_client.py
│   │   └── broker_interface.py
│   │
│   ├── strategy/
│   │   ├── base_strategy.py
│   │   ├── momentum_strategy.py
│   │   └── mean_reversion_strategy.py
│   │
│   ├── risk/
│   │   ├── risk_manager.py
│   │   └── position_sizing.py
│   │
│   ├── execution/
│   │   ├── order_manager.py
│   │   └── trade_monitor.py
│   │
│   ├── backtest/
│   │   ├── backtester.py
│   │   └── metrics.py
│   │
│   ├── logging/
│   │   └── trade_logger.py
│   │
│   └── utils/
│       ├── time_utils.py
│       └── news_filter.py
│
├── tests/
│   ├── test_risk_manager.py
│   ├── test_position_sizing.py
│   ├── test_strategy.py
│   └── test_backtester.py
│
└── requirements.txt
```

---

# 8. Konfigūracijos pavyzdys

## config/risk.yaml

```yaml
account_currency: "EUR"

risk:
  risk_per_trade_pct: 0.5
  max_daily_loss_pct: 2.0
  max_weekly_loss_pct: 5.0
  max_total_drawdown_pct: 10.0
  max_consecutive_losses: 3
  max_trades_per_day: 5
  max_open_positions: 1

trade:
  symbol: "XAUUSD"
  timeframe: "M1"
  max_trade_duration_minutes: 5
  use_stop_loss: true
  use_take_profit: true
  allow_martingale: false
  allow_grid: false

spread:
  max_spread_points: 30

execution:
  demo_mode: true
  paper_trading: true
  allow_live_trading: false
```

## config/strategy.yaml

```yaml
strategy:
  name: "basic_momentum"
  enabled: true

session:
  timezone: "Europe/Vilnius"
  start_time: "10:00"
  end_time: "18:00"

news_filter:
  enabled: true
  block_minutes_before: 30
  block_minutes_after: 30

signal:
  lookback_candles: 5
  min_momentum_points: 50
  stop_loss_points: 70
  take_profit_points: 100
```

---

# 9. Draudžiami boto veiksmai

Botui negalima:

- naudoti martingale;
- didinti lotą po pralaimėjimo;
- atidaryti grid pozicijų be stop-loss;
- prekiauti be SL;
- prekiauti per svarbias naujienas;
- atidaryti daugiau nei vieną poziciją vienu metu;
- ignoruoti dienos nuostolio limitą;
- tęsti prekybą po brokerio klaidos;
- naudoti realią sąskaitą, kol demo testas nepraeitas;
- keisti strategijos parametrus kasdien pagal emociją.

---

# 10. Minimalus MVP

Pirmoji veikianti versija turi turėti:

- config failus;
- paper trading režimą;
- signalų generavimą;
- spread filtrą;
- risk manager;
- position size skaičiavimą;
- trade logger;
- backtest modulį;
- demo trading režimą;
- kill switch mechanizmą.

---

# 11. Galutinis 3 mėn. sprendimas

Po 3 mėn. galimi sprendimai:

## Tęsti

Jeigu:

- botas laikėsi taisyklių;
- drawdown buvo mažas;
- strategija nenuostolinga po kaštų;
- realūs rezultatai panašūs į demo;
- nėra kritinių techninių klaidų.

## Taisyti

Jeigu:

- strategija turi potencialo, bet ją valgo spread'as;
- signalai per dažni arba per reti;
- demo ir real rezultatai skiriasi;
- reikia gerinti filtrus.

## Stabdyti

Jeigu:

- botas praranda kontrolę;
- viršijami rizikos limitai;
- nėra jokio statistinio pranašumo;
- pelnas priklauso nuo vienos atsitiktinės dienos;
- reali prekyba kardinaliai blogesnė už backtestą.

---

# 12. Pagrindinė filosofija

Botas neturi būti kuriamas kaip „pasyvių pajamų mašina“.

Jis turi būti kuriamas kaip:

```text
Kontroliuojama testavimo sistema, kuri pirmiausia saugo kapitalą, renka statistiką ir leidžia priimti sprendimus pagal duomenis.
```

Pirmų 3 mėnesių sėkmė:

```text
Botas išgyveno, laikėsi taisyklių, nesudegino sąskaitos ir pateikė aiškią statistiką.
```
