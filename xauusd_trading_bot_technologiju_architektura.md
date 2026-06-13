# XAU/USD prekybos platformos technologijų architektūra

## 1. Pagrindinis sprendimas

| Sritis | Technologija |
|---|---|
| Web frontend | TypeScript, React, Next.js |
| Valdymo API | Python, FastAPI, Pydantic |
| Strategijos ir rizikos domenas | Python |
| Rinkos duomenys | OANDA Practice API |
| 24/7 collector | Python Linux konteineris |
| Duomenų bazė | PostgreSQL |
| Laiko eilučių plėtra | PostgreSQL particijos, vėliau TimescaleDB |
| Cache ir darbų eilės | Redis tik kai atsiranda realus poreikis |
| Hostingas shadow/paper etapui | Railway |
| Production plėtra | Valdomi Linux konteineriai ir PostgreSQL |

```text
OANDA Practice API
        |
        v
market-data collector
        |
        v
FastAPI -> PostgreSQL
   |
   +-> WebSocket -> Next.js UI
   |
   +-> Python strategy domain
```

OANDA yra vienintelis dabartinis išorinis rinkos duomenų šaltinis. Strategijos
ir rizikos moduliai dirba tik su kanoniniais Goldie modeliais ir nežino OANDA
atsakymų formato.

## 2. Atsakomybių ribos

### Frontend

- autentifikacija ir valdymo ekranai;
- botų, konfigūracijų, signalų ir būsenų rodymas;
- jokios savarankiškos prekybos logikos;
- jokio tiesioginio ryšio su duomenų ar vykdymo tiekėjais.

### FastAPI

- naudotojų ir botų valdymas;
- nekintamos konfigūracijų versijos;
- feed registracija ir autorizuotas ingest;
- duomenų validacija bei PostgreSQL įrašymas;
- strategijos paleidimas gavus užbaigtą M1 žvakę;
- REST istorija ir WebSocket pranešimai.

### Market-data collector

- OANDA instrumento prieinamumo patikra;
- XAU_USD bid/ask pricing stream;
- paskutinio quote išsaugojimas kas penkias sekundes;
- tik užbaigtos midpoint M1 žvakės;
- 30 dienų pradinis backfill;
- heartbeat, reconnect ir `MARKET_CLOSED` būsena;
- jokios pavedimų, pozicijų ar sąskaitos valdymo sąsajos.

### Trading domain

Tas pats strategijos interfeisas turi būti naudojamas replay, backtest, shadow,
paper ir galimame būsimame live režime:

```python
class Strategy(Protocol):
    def evaluate(self, context: MarketContext) -> SignalDecision:
        ...
```

Strategija grąžina pasiūlymą ir niekada tiesiogiai nekviečia išorinio tiekėjo.
Risk manager turi likti grynas Python modulis be FastAPI ir OANDA
priklausomybių.

## 3. Duomenų modelis

PostgreSQL yra pagrindinis tiesos šaltinis.

- `market_feeds` aprašo OANDA aplinką ir simbolį;
- `instrument_specifications` saugo provider-neutral metaduomenis;
- `market_ticks` saugo penkių sekundžių quote istoriją;
- `candles` saugo užbaigtas M1 žvakes;
- keli botai naudoja tą patį feed nedubliuojant rinkos duomenų;
- `paper_accounts` priklauso Goldie ir nėra brokerio sąskaitos kopija;
- signalai, konfigūracijų versijos ir auditas yra append-only;
- finansinės reikšmės saugomos `numeric`, laikas UTC.

Penkių sekundžių quotes laikomi 30 dienų. M1 žvakės saugomos neribotai.
TimescaleDB pridedama tik kai PostgreSQL indeksų ir particijų nebepakanka.

## 4. Shadow ir paper

### Shadow

- naudoja realius OANDA rinkos duomenis;
- generuoja teorinius signalus;
- neturi virtualaus balanso;
- nekuria pavedimų.

### Paper

- naudoja tą patį rinkos feed ir strategijos kodą;
- pradinis Goldie balansas yra 10 000 USD;
- balansas nepriklauso nuo jokios išorinės demo sąskaitos;
- kol nėra fill variklio, balansas, equity ir available cash nekinta.

Paper fill, slippage, commission ir pozicijų būsenų mašina bus atskiras domeno
etapas. Jis negali būti įgyvendintas frontend ar collector procese.

## 5. Railway topologija

Viename Railway projekte:

```text
web
api
market-data-collector
maintenance cron
PostgreSQL
```

- API ir collector laikomi po vieną repliką;
- API paleidžia Alembic migracijas prieš Uvicorn;
- collector restart policy yra `ALWAYS`;
- maintenance kasdien šalina senesnius nei 30 dienų quotes;
- secrets laikomi Railway variables;
- UI ir API vieši tik per HTTPS;
- collector su API bendrauja privačiu Railway tinklu.

API kol kas negalima horizontaliai dauginti, nes WebSocket fan-out laikomas
proceso atmintyje. Prieš scaling jį reikia perkelti į Redis ar kitą bendrą
transportą.

## 6. Saugumas

- OANDA token laikomas tik collector secrets;
- frontend negauna providerio credentials;
- collector į Goldie API jungiasi su atskiru service token;
- visi ingest endpointai validuoja feed ir agento atitikimą;
- nėra order, trade, position ar execution endpointų;
- production DB neviešinama internete;
- auditui naudojama PostgreSQL, ne Redis ar aplikacijos logai.

## 7. Testavimas

### Python

- `pytest`;
- OANDA atsakymų fixtures be realaus tinklo CI metu;
- bid/ask ir M1 normalizavimo testai;
- backfill ir deduplikavimo testai;
- stale, reconnect ir market-closed testai;
- kelių botų bendro feed testas;
- PAPER ledger testas;
- automatinė patikra, kad nėra vykdymo API.

### TypeScript

- Vitest;
- React Testing Library;
- TypeScript strict mode;
- production Next.js build.

### Migracijos

- švarios DB migracija;
- seno lokalaus prototipo DB migracija;
- seni brokerio account, symbol ir market įrašai neperkeliami;
- PAPER botams sukuriamas 10 000 USD Goldie ledger.

## 8. Plėtros etapai

### Etapas A: hosted shadow

- Railway web, API, PostgreSQL ir collector;
- OANDA quotes ir M1 istorija;
- teoriniai signalai;
- monitoring ir retention.

### Etapas B: pilnas paper

- event-driven paper fill variklis;
- pozicijos, komisija, slippage ir PnL;
- centralizuotas risk manager;
- replay ir backtest su tuo pačiu strategijos kodu.

### Etapas C: produkcinis pasirengimas

- valdomas PostgreSQL su point-in-time restore;
- object storage Parquet istorijai;
- centralizuotos metrikos ir incidentai;
- infrastruktūra kaip kodas;
- atskiri staging ir production.

### Etapas D: galimas live vykdymas

Live vykdymas nėra dabartinio projekto dalis. Jei jis bus patvirtintas, kuriamas
atskiras provider-neutral execution adapteris su idempotency, reconciliation,
risk veto ir kill switch. Rinkos duomenų collector išlieka read-only.

## 9. Architektūriniai draudimai

- Jokia prekybos taisyklė negali egzistuoti tik frontend.
- Collector negali pateikti pavedimų.
- Joks būsimas pavedimas negali apeiti centralizuoto risk manager.
- Redis negali būti finansinių įrašų tiesos šaltinis.
- Backtest ir paper/live negali skirtingai interpretuoti strategijos.
- Rinkos duomenys negali būti tyliai redaguojami.
- Providerio credentials negali patekti į naršyklę.
- Production DB negali būti viešai prieinama internete.
