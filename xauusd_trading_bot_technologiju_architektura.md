# XAU/USD Trading Platform technologijų architektūra

## 1. Trumpa rekomendacija

Pagrindinis technologijų pasirinkimas:

| Sritis | Technologija |
|---|---|
| Web frontend | TypeScript, React, Next.js |
| Valdymo API | Python, FastAPI, Pydantic |
| Prekybos ir rizikos branduolys | Python |
| MT5 vykdymo agentas | Python + MetaTrader5 paketas Windows aplinkoje |
| Backtest ir analitika | Python, Polars, NumPy, Pandas, Numba |
| Pagrindinė duomenų bazė | PostgreSQL |
| Laiko eilučių optimizacija | PostgreSQL particijos, vėliau TimescaleDB |
| Greita laikina būsena | Redis |
| Ilgos užduotys | Celery arba Dramatiq su Redis |
| Istoriniai dideli duomenys | Parquet objektų saugykloje |
| Realaus laiko UI | WebSocket arba Server-Sent Events |
| Autentifikacija | OIDC/OAuth2, Microsoft Entra ID arba Keycloak |
| Konteineriai | Docker ir Docker Compose |
| CI/CD | GitHub Actions |
| Infrastruktūra | Azure, valdoma per Terraform |
| Stebėjimas | OpenTelemetry, Azure Monitor, Sentry |

Svarbiausias architektūrinis sprendimas:

```text
Windows execution plane
    MetaTrader 5 Terminal
    Python MT5 Agent
            |
            | TLS, outbound connection
            v
Linux control plane
    Next.js UI
    FastAPI
    Background workers
    PostgreSQL
    Redis
    Object storage
```

MT5 vykdymo dalis turi veikti Windows mašinoje su įdiegtu MetaTrader 5
terminalu. UI, API, duomenų bazė ir analitika neturi būti priklausomi nuo
Windows ar paties MT5 terminalo.

## 2. Kodėl ne viską rašyti viena kalba

### TypeScript naudojamas UI

TypeScript geriausiai tinka:

- sudėtingoms konfigūracijos formoms;
- realaus laiko dashboard;
- tipizuotam bendravimui su API;
- didelėms lentelėms;
- grafikams;
- naudotojų rolėms ir UI būsenoms.

### Python naudojamas prekybos domene

Python geriausiai tinka:

- MT5 integracijai;
- strategijos skaičiavimams;
- risk manager;
- backtest;
- statistikai;
- duomenų apdorojimui;
- eksperimentams ir galimam machine learning.

Nerekomenduojama strategijos logikos dubliuoti TypeScript kode. Frontend
gali rodyti backend apskaičiuotas reikšmes, bet negali savarankiškai priimti
prekybos sprendimo.

## 3. Frontend technologijos

### 3.1. Bazinis stack

- `TypeScript`
- `React`
- `Next.js`
- `Tailwind CSS`
- `shadcn/ui` arba nuosavas komponentų sluoksnis ant `Radix UI`

Next.js parenkamas dėl:

- aiškios aplikacijos struktūros;
- server-side autentifikacijos galimybių;
- patogaus maršrutizavimo;
- gero Docker ir debesijos palaikymo;
- galimybės dalį puslapių generuoti serveryje.

Tai turi būti web aplikacija, ne Electron desktop programa. MT5 agentas veiks
atskirai ir su UI komunikuos per backend.

### 3.2. Frontend bibliotekos pagal funkciją

| Funkcija | Technologija |
|---|---|
| Serverio būsena | TanStack Query |
| Lokalios UI būsenos | Zustand |
| Formos | React Hook Form |
| Validacija | Zod |
| Lentelės | TanStack Table |
| Kainos grafikai | TradingView Lightweight Charts |
| Analitiniai grafikai | Apache ECharts |
| Datos | Luxon arba date-fns-tz |
| API tipai | OpenAPI generuojamas TypeScript klientas |
| Testai | Vitest, React Testing Library |
| End-to-end testai | Playwright |
| Komponentų katalogas | Storybook |

`Redux` pradžioje nereikalingas. Dauguma duomenų yra serverio būsena, todėl
TanStack Query yra tinkamesnis pagrindinis mechanizmas.

### 3.3. Realaus laiko duomenys

Naudoti:

- `WebSocket` boto, signalų, pavedimų ir incidentų srautui;
- REST API istorijai, filtravimui, konfigūracijai ir komandoms;
- polling kaip atsarginį mechanizmą, jei nutrūksta WebSocket.

Kiekvienas realaus laiko pranešimas turi:

- `event_id`;
- `event_type`;
- `occurred_at`;
- `bot_instance_id`;
- `run_id`;
- duomenų schemos versiją.

UI privalo mokėti po ryšio atkūrimo paprašyti praleistų įvykių.

## 4. Backend valdymo API

### 4.1. Bazinis stack

- `Python`
- `FastAPI`
- `Pydantic`
- `SQLAlchemy 2`
- `Alembic`
- `Uvicorn`

FastAPI parenkamas, nes:

- naudoja Python tipų anotacijas;
- turi OpenAPI generavimą;
- Pydantic tinka konfigūracijų validacijai;
- palaiko async I/O;
- frontend klientą galima generuoti iš OpenAPI schemos.

### 4.2. Modulinis monolitas

MVP turi būti modulinis monolitas, ne mikroservisų sistema.

Siūlomi backend moduliai:

```text
apps/api
apps/worker
apps/mt5_agent

packages/domain
├── bots
├── strategies
├── risk
├── execution
├── signals
├── portfolio
├── backtests
├── analytics
├── incidents
├── reports
└── identity
```

Kiekvienas modulis turi savo:

- domeno modelius;
- application servisus;
- repository sąsajas;
- API schemas;
- testus.

Mikroservisus verta svarstyti tik tada, kai skirtingų komponentų apkrova ar
atsakomybės realiai pradeda trukdyti vienam deployment.

### 4.3. API stilius

Rekomenduojamas REST API:

```text
/api/v1/bots
/api/v1/bot-runs
/api/v1/strategies
/api/v1/risk-profiles
/api/v1/signals
/api/v1/orders
/api/v1/trades
/api/v1/backtests
/api/v1/incidents
/api/v1/reports
/api/v1/commands
```

GraphQL pradžioje nereikalingas. REST su aiškiais filtrais ir OpenAPI bus
paprastesnis auditui, testavimui ir tipų generavimui.

## 5. Prekybos branduolys

### 5.1. Kalba ir bibliotekos

Naudoti Python:

- `dataclasses` arba Pydantic nekintamiems komandų modeliams;
- `Decimal` pinigams ir rizikos limitams;
- `NumPy` indikatoriams;
- `Polars` didesnių duomenų transformacijoms;
- `Pandas` tik ten, kur reikalinga bibliotekų ekosistema;
- `Numba` tik išmatuotiems backtest našumo taškams.

### 5.2. Bendras strategijos kodas

Tas pats `Strategy` interfeisas turi būti naudojamas:

- backtest;
- replay;
- shadow;
- paper;
- demo;
- live režimuose.

```python
class Strategy(Protocol):
    def evaluate(self, context: MarketContext) -> SignalDecision:
        ...
```

Strategija grąžina pasiūlymą. Ji neturi teisės tiesiogiai kviesti brokerio.

### 5.3. Risk manager

Risk manager turi būti grynas Python domeno modulis be FastAPI ir MT5
priklausomybių. Jį turi būti galima testuoti perduodant paprastus objektus.

Jis apskaičiuoja:

- ar signalas leidžiamas;
- maksimalų lotą;
- planuojamą piniginę riziką;
- portfelio riziką;
- veto priežastis;
- kill switch būseną.

### 5.4. Pavedimų būsenų mašina

Galima naudoti:

- aiškiai aprašytą Python `Enum` ir transition servisą;
- `transitions` biblioteką tik jei būsenų valdymas tampa sudėtingas.

Finansinei logikai geriau pradėti nuo nuosavo nedidelio, griežtai testuojamo
transition modulio nei nuo sunkios workflow platformos.

## 6. MT5 execution agent

### 6.1. Technologija

- Windows Server arba Windows 11 VM;
- įdiegtas MetaTrader 5 terminalas;
- Python;
- oficialus `MetaTrader5` Python paketas;
- Windows Service per `NSSM`, `WinSW` arba Python service wrapper;
- struktūrizuoti JSON logai.

Agentas atsakingas tik už:

- terminalo ir sąskaitos būseną;
- rinkos duomenų gavimą;
- simbolio specifikaciją;
- pavedimo patikrą ir pateikimą;
- pozicijų, pavedimų ir istorijos reconciliaciją;
- heartbeat;
- backend komandų vykdymą.

### 6.2. Saugus ryšys

Agentas turi pats inicijuoti išeinantį TLS ryšį į valdymo platformą. Nereikia
atidaryti viešo inbound porto Windows VM.

Pradžioje galima naudoti:

- periodinį HTTPS command polling;
- WebSocket įvykiams ir greitesniam komandų gavimui;
- trumpalaikius agento sertifikatus ar rotuojamus service token.

Vėliau durable komandų kanalui galima naudoti NATS JetStream.

### 6.3. Keli botai ir sąskaitos

Saugiausia taisyklė:

- viena MT5 terminalo instancija vienai brokerio sąskaitai;
- keli botai gali naudoti tą sąskaitą tik per vieną execution agentą;
- agentas centralizuotai serializuoja pavedimus;
- kiekvienas botas turi unikalų `magic_number`.

Skirtingų brokerių ar live/demo sąskaitų terminalai turi atskirus katalogus
ir procesus.

### 6.4. Ko nedaryti

- Neleisti frontend tiesiogiai jungtis prie MT5.
- Nelaikyti brokerio slaptažodžių web naršyklėje.
- Nesiųsti `order_send` iš API konteinerio.
- Nepaleisti kelių nekontroliuojamų Python procesų prie tos pačios sąskaitos.
- Nelaikyti Windows VM vieninteliu istorinių duomenų šaltiniu.

## 7. Duomenų bazės

### 7.1. PostgreSQL kaip pagrindinis tiesos šaltinis

PostgreSQL saugo:

- naudotojus ir roles;
- botų instancijas;
- konfigūracijų versijas;
- run;
- signalus ir jų sprendimus;
- pavedimus, fill ir sandorius;
- risk snapshots;
- incidentus;
- audit log;
- backtest metaduomenis;
- ataskaitų metaduomenis.

### 7.2. Schemos principai

- visur naudoti UUID;
- laiką saugoti `timestamptz` UTC;
- pinigams naudoti `numeric`, ne `float`;
- istorinius įrašus papildyti, o ne perrašyti;
- dideles įvykių lenteles particionuoti pagal laiką;
- visiems įrašams turėti `workspace_id`, `bot_instance_id` ir `run_id`, kai taikoma.

### 7.3. TimescaleDB

MVP pradžioje nebūtina.

Pridėti, kai:

- saugoma daug tick duomenų;
- reikalingos greitos laiko intervalų agregacijos;
- įprastos PostgreSQL particijos ir indeksai nebeatitinka našumo poreikio.

### 7.4. Redis

Redis naudoti:

- trumpalaikiam cache;
- rate limiting;
- Celery/Dramatiq job queue;
- WebSocket fan-out;
- trumpalaikiams distributed lock.

Redis negali būti:

- vienintelis pavedimų istorijos šaltinis;
- vienintelis kill switch būsenos šaltinis;
- vienintelė komandų audito vieta.

Kritinės būsenos pirmiausia įrašomos PostgreSQL.

### 7.5. Objektų saugykla ir Parquet

Azure Blob Storage arba S3 suderinamoje saugykloje laikyti:

- raw ticks;
- istorinius candles;
- Parquet duomenų rinkinius;
- backtest artefaktus;
- PDF ataskaitas;
- incidentų flight recorder paketus;
- didelius eksportus.

PostgreSQL saugo failo metaduomenis, hash, schemos versiją ir saugyklos raktą.

## 8. Backtest ir analitikos technologijos

### 8.1. Backtest variklis

Rekomenduojamas nuosavas event-driven backtest branduolys, naudojantis tą
pačią strategijos ir risk manager sąsają kaip live botas.

Bibliotekos:

- Polars;
- NumPy;
- PyArrow;
- Numba;
- SciPy;
- Statsmodels.

`vectorbt`, `Backtrader` ar analogus galima naudoti prototipams ir rezultatų
palyginimui, bet ne kaip vienintelį produkto vykdymo modelį. Svarbu tiksliai
atkartoti bid/ask, SL/TP, slippage ir brokerio taisykles.

### 8.2. Ilgos užduotys

Backtest, eksportai ir ataskaitos vykdomi background worker:

- MVP: Celery + Redis;
- alternatyva: Dramatiq + Redis;
- didesnei sistemai: atskiri konteinerių job per Azure Container Apps Jobs.

API tik sukuria užduotį ir grąžina `job_id`. Progresas saugomas DB ir
transliuojamas UI.

### 8.3. Notebook aplinka

Tyrimams galima turėti atskirą JupyterLab aplinką, tačiau:

- ji negali turėti live brokerio pavedimų teisių;
- analizės kodas nėra production strategijos pakaitalas;
- patvirtinta strategija perkeliama į testuojamą Python modulį.

## 9. Autentifikacija ir saugumas

### 9.1. Identity provider

Jei naudojamas Azure:

- Microsoft Entra ID;
- atskiros application roles;
- MFA administratoriams, operatoriams ir risk manager.

Jei reikalingas savarankiškai valdomas sprendimas:

- Keycloak.

Nerekomenduojama pačiam kurti slaptažodžių autentifikacijos sistemos.

### 9.2. Secrets

- production: Azure Key Vault;
- lokaliai: `.env`, kuris neįtrauktas į Git;
- agentui: Windows Credential Manager arba apsaugotas service secret;
- slapti duomenys niekada negrąžinami frontend.

### 9.3. Auditas

Kiekviena komanda turi:

- `command_id`;
- naudotoją arba agentą;
- rolę;
- laiką;
- tikslinį botą;
- prieš ir po būseną;
- priežastį;
- backend rezultatą.

## 10. Stebėjimas

### 10.1. Instrumentacija

- OpenTelemetry traces, metrics ir logs;
- struktūrizuoti JSON logai;
- correlation ID per UI, API, worker ir agentą;
- Azure Application Insights arba Grafana stack.

### 10.2. Klaidos

Sentry naudoti:

- frontend JavaScript klaidoms;
- backend exception;
- release ir source map sekimui.

Sentry nėra pagrindinis prekybos audito žurnalas.

### 10.3. Infrastruktūros metrikos

Stebėti:

- agent heartbeat;
- MT5 terminalo ryšį;
- paskutinio tick amžių;
- komandų eilės gylį;
- API latency ir error rate;
- worker užduočių trukmę;
- DB jungčių skaičių;
- disko ir atminties naudojimą;
- WebSocket klientų skaičių.

## 11. Testavimo technologijos

### Python

- `pytest`;
- `pytest-asyncio`;
- `Hypothesis` risk ir position sizing property testams;
- `testcontainers` PostgreSQL ir Redis integracijai;
- `freezegun` arba kontroliuojamas clock laiko testams;
- `mypy`;
- `ruff`;
- `coverage.py`.

### TypeScript

- `Vitest`;
- React Testing Library;
- Playwright;
- `eslint`;
- TypeScript strict mode.

### MT5

Sukurti `FakeBrokerAdapter`, kuris modeliuoja:

- fill;
- partial fill;
- reject;
- timeout;
- ryšio dingimą;
- SL uždėjimo klaidą;
- proceso perkrovimą;
- netikėtą atvirą poziciją.

Automatiniai testai neturi priklausyti nuo realaus brokerio pasiekiamumo.

## 12. Lokali kūrimo aplinka

Linux dalis paleidžiama per Docker Compose:

```text
frontend
api
worker
postgres
redis
object-storage-emulator
```

MT5 agentas kuriamas ir testuojamas Windows:

```text
MetaTrader 5 Terminal
Python virtual environment
MT5 Agent
```

MinIO galima naudoti lokaliam S3 tipo object storage modeliavimui.

## 13. Hostingas

## 13.1. Rekomenduojamas Azure variantas

### Windows execution plane

`Azure Windows VM`:

- MT5 terminalui;
- Python execution agentui;
- atskiram Windows vartotojui;
- automatiniam paleidimui po reboot;
- regionui, esančiam kuo arčiau brokerio serverio.

Regionas parenkamas ne pagal naudotojo gyvenamą vietą, o pamatuojant latency
iki brokerio prekybos serverio. Europoje pirmiausia verta išmatuoti:

- Poland Central;
- North Europe;
- Sweden Central;
- West Europe.

### Linux control plane

`Azure Container Apps`:

- FastAPI;
- Next.js;
- background worker;
- scheduled jobs.

Privalumas: HTTPS, secrets, revision, autoscaling ir mažiau serverių priežiūros.

### Duomenys

- `Azure Database for PostgreSQL Flexible Server`;
- `Azure Cache for Redis` arba kitas valdomas Redis;
- `Azure Blob Storage`;
- `Azure Key Vault`;
- `Azure Monitor` ir `Application Insights`.

### Tinklas

- viena Azure VNet;
- PostgreSQL privatus endpoint;
- API viešas tik per HTTPS;
- Windows agentas jungiasi outbound;
- administracinė Windows prieiga ribojama VPN, Bastion arba konkrečiu IP;
- MT5 terminalo portai neviešinami.

## 13.2. Pigesnis MVP variantas

Pradiniam shadow/demo etapui:

### Windows VPS

- viena Windows VPS su MT5 ir Python agentu;
- teikėjas turi leisti Windows licenciją ir stabilų 24/7 veikimą;
- regionas parenkamas pagal brokerio latency.

### Linux VPS

Viena Linux VPS su Docker Compose:

- Next.js;
- FastAPI;
- worker;
- PostgreSQL;
- Redis;
- Caddy arba Traefik;
- automatinės šifruotos atsarginės kopijos į object storage.

Šis variantas pigesnis, bet reikia pačiam:

- diegti OS atnaujinimus;
- stebėti diską;
- konfigūruoti backup;
- atkurti DB;
- valdyti TLS;
- reaguoti į serverio gedimus.

Jis tinkamas MVP ir demo, bet live prekybai valdomas PostgreSQL yra saugesnis.

## 13.3. Ko nerekomenduoju hostingui

- Vien Vercel: netinka MT5 ir nuolat veikiančiam execution agentui.
- Vien shared hosting: nėra tinkamos procesų ir saugumo kontrolės.
- Vien serverless funkcijos: execution agentui reikia nuolatinio proceso ir MT5 terminalo.
- Kubernetes MVP etape: per didelė eksploatavimo našta.
- Namų kompiuteris live prekybai: elektros, interneto ir perkrovimų rizika.
- Viena Windows VM viskam: web, DB ir MT5 gedimai taptų viena bendra gedimo vieta.

Vercel galima naudoti tik frontend, bet vieno debesijos tiekėjo Azure
variantas pradžioje sumažina autentifikacijos, tinklo ir incidentų sudėtingumą.

## 14. Diegimo etapai

### Etapas A: lokalus prototipas

- frontend ir API lokaliai;
- PostgreSQL ir Redis per Docker Compose;
- MT5 agentas kūrėjo Windows kompiuteryje;
- tik backtest, replay ir shadow.

### Etapas B: nuolatinis demo

- Windows VM/VPS su MT5 agentu;
- Linux control plane debesyje;
- valdoma arba reguliariai kopijuojama PostgreSQL;
- Blob Storage;
- monitoring ir perspėjimai.

### Etapas C: ribotas live

- atskirta demo ir live Windows VM arba bent terminalų bei credential aplinka;
- valdomas PostgreSQL su point-in-time restore;
- Key Vault;
- privatus tinklas;
- centralizuoti logai;
- automatiniai backup ir atkūrimo testas;
- infrastruktūra aprašyta Terraform;
- atskiras staging ir production.

### Etapas D: keli brokeriai ir didesnė apkrova

- execution agent pool;
- NATS JetStream patikimam event transportui;
- atskiri backtest worker;
- TimescaleDB ar atskiras analitinis sluoksnis;
- read replica analitikai;
- blue/green deployment;
- disaster recovery kitame regione.

## 15. CI/CD

GitHub Actions pipeline:

1. lint ir type-check;
2. unit testai;
3. integraciniai testai;
4. frontend build;
5. Docker image build;
6. dependency ir container vulnerability scan;
7. deployment į staging;
8. smoke test;
9. rankinis production patvirtinimas;
10. deployment su migracijų kontrole.

Live execution agentas neturi būti automatiškai perkraunamas prekybos metu.
Deployment tikrina, ar nėra atviros pozicijos, arba naudoja kontroliuojamą
handover procedūrą.

## 16. Monorepo struktūra

```text
goldie/
├── apps/
│   ├── web/                 # Next.js, TypeScript
│   ├── api/                 # FastAPI
│   ├── worker/              # Background jobs
│   └── mt5-agent/           # Windows execution agent
├── packages/
│   ├── trading-domain/      # Strategy, risk, execution rules
│   ├── backtest/
│   ├── analytics/
│   ├── db/
│   └── api-client/          # Generated TypeScript client
├── infrastructure/
│   ├── docker/
│   ├── terraform/
│   └── github-actions/
├── tests/
│   ├── integration/
│   ├── e2e/
│   └── fixtures/
└── docs/
```

Python paketams naudoti `uv` arba Poetry. Mano pasirinkimas naujam projektui:
`uv`, nes jis greitas ir gali valdyti virtualias aplinkas bei lock failą.

TypeScript paketams naudoti `pnpm`.

## 17. Konkretus pasirinkimas šiam projektui

Jei projektą pradėčiau dabar, rinkčiausi:

```text
Frontend:
  Next.js + TypeScript + Tailwind + shadcn/ui
  TanStack Query + TanStack Table
  Lightweight Charts + ECharts

Backend:
  Python + FastAPI + Pydantic
  SQLAlchemy + Alembic
  Celery + Redis

Trading:
  Python domain package
  MetaTrader5 package
  Polars + NumPy + PyArrow
  Decimal risk calculations

Data:
  PostgreSQL
  Redis
  Parquet in Azure Blob Storage

Hosting:
  Azure Windows VM for MT5 Agent
  Azure Container Apps for web/api/worker
  Azure Database for PostgreSQL
  Azure Blob Storage
  Key Vault
  Application Insights

Delivery:
  Docker
  Terraform
  GitHub Actions
```

## 18. Sprendimų matrica pagal funkcinį reikalavimą

| Funkcinė sritis | Technologinis sprendimas |
|---|---|
| Kelių botų valdymas | FastAPI, PostgreSQL, Next.js |
| Konfigūracijų versijos | PostgreSQL append-only lentelės, Pydantic, Zod |
| Realaus laiko monitorius | WebSocket, Redis fan-out, React |
| Signalų generavimas | Python strategy package, NumPy/Polars |
| Risk manager | Grynas Python domeno modulis, Decimal |
| Portfelio rizika | PostgreSQL transakcijos ir centralizuotas Python servisas |
| MT5 pavedimai | Windows agentas, MetaTrader5 Python paketas |
| Pavedimų idempotency | PostgreSQL unique constraints ir command ID |
| Kill switch | PostgreSQL būsenos mašina, agento lokalus fail-safe cache |
| Backtest | Python event-driven engine, Polars, NumPy, PyArrow |
| Ilgi backtest | Celery worker arba Container Apps Jobs |
| Analitika | SQL agregacijos, Polars, ECharts |
| Tick istorija | Parquet ir Blob Storage |
| Audit log | PostgreSQL append-only įvykių lentelė |
| Incidentai | FastAPI domeno modulis, PostgreSQL, UI timeline |
| Perspėjimai | Worker, el. paštas, Telegram/Teams adapteriai |
| Ataskaitos | Python, Jinja2, Playwright PDF arba WeasyPrint |
| Autentifikacija | Entra ID, OIDC, MFA |
| Secrets | Azure Key Vault |
| Monitoring | OpenTelemetry, Application Insights, Sentry |
| Backup | PostgreSQL PITR ir Blob lifecycle policy |
| CI/CD | GitHub Actions, Docker, Terraform |

## 19. Architektūriniai draudimai

- Jokia prekybos taisyklė negali egzistuoti tik frontend.
- Joks live pavedimas negali apeiti centralizuoto risk manager.
- Redis negali būti finansinių įrašų tiesos šaltinis.
- MT5 agentas negali savarankiškai keisti strategijos konfigūracijos.
- Backtest ir live negali turėti skirtingų strategijos interpretacijų.
- Live duomenys negali būti tyliai redaguojami.
- Infrastructure pakeitimai neturi būti daromi tik rankiniu būdu portale.
- Production DB negali būti viešai prieinama internete.

## 20. Galutinis vertinimas

Šiam produktui racionaliausias derinys yra:

- TypeScript ir React naudotojo sąsajai;
- Python visai prekybos ir analitikos logikai;
- PostgreSQL ilgalaikei būsenai;
- Windows VM tik MT5 vykdymui;
- Linux konteineriai likusiai platformai;
- Azure kaip pagrindinis production hostingas.

Tai palieka galimybę pradėti nedideliu MVP, tačiau nereikalauja perrašyti
trading branduolio, kai atsiras daugiau botų, brokerių ar naudotojų.
