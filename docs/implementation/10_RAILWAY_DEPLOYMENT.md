# Railway diegimo instrukcija

Ši instrukcija aprašo pilną Goldie `SHADOW`, `PAPER`, backtest ir Redis Stream
ingestion diegimą Railway platformoje.

## Architektūra

Viename Railway projekte sukurkite aštuonis servisus:

1. PostgreSQL.
2. Redis.
3. `api`.
4. `web`.
5. `market-data-collector`.
6. `ingestion-worker`.
7. `worker` backtestams.
8. `maintenance`.

PostgreSQL yra pagrindinis duomenų tiesos šaltinis. Redis naudojamas:

- rinkos duomenų transportui per Redis Streams;
- trumpalaikiam `/collector` dashboard cache;
- backtest worker pažadinimui;
- WebSocket įvykių platinimui per Pub/Sub.

`market-data-collector` renka OANDA duomenis. Pradinio diegimo metu juos siunčia
į API per HTTP, o po patikrinimo persijungia į Redis Stream.
`ingestion-worker` skaito Stream įvykius ir įrašo juos į PostgreSQL.
`worker` vykdo tik backtestus, todėl ilgas backtestas nestabdo rinkos duomenų.

## Bendros Railway taisyklės

- PostgreSQL ir Redis naudokite per Railway private networking.
- Kintamuosius rinkitės per Railway reference autocomplete.
- Nekopijuokite viešų PostgreSQL ar Redis adresų, jeigu servisai yra tame
  pačiame Railway projekte ir environment.
- Pradžioje kiekvienam aplikacijos servisui naudokite po vieną replica.
- Kiekvieno serviso Settings skiltyje nurodykite jo Config File.

## PostgreSQL

Sukurkite Railway PostgreSQL servisą. Viešas TCP adresas Goldie servisams
nereikalingas.

API, ingestion worker, backtest worker ir maintenance turi naudoti tą patį
privatų `DATABASE_URL`.

API nustatymai automatiškai normalizuoja Railway `postgresql://` arba
`postgres://` URL į SQLAlchemy naudojamą `postgresql+psycopg://` schemą.
Railway reference reikšmės rankiniu būdu keisti nereikia.

```text
DATABASE_URL=${{Postgres.DATABASE_URL}}
```

## Redis

Sukurkite Railway Redis servisą. API, collector ir abu workeriai turi naudoti
privatų Redis URL.

Goldie naudoja šiuos Redis objektus:

```text
goldie:ingestion:v1
goldie-ingestion
goldie:events
collector:overview:v1
goldie:ingestion-worker:heartbeat
```

## API servisas

Railway nustatymai:

```text
Service name: api
Root Directory: repository root
Config File: /railway/api.toml
Replicas: 1
```

Kintamieji:

```text
DATABASE_URL=<Railway private PostgreSQL URL>
REDIS_URL=<Railway private Redis URL>
JWT_SECRET=<ilga atsitiktinė reikšmė>
LOCAL_ADMIN_EMAIL=<administratoriaus el. paštas>
LOCAL_ADMIN_PASSWORD=<stiprus slaptažodis>
AGENT_SERVICE_TOKEN=<ilga bendra collector ir API reikšmė>
CORS_ORIGINS=https://<web-public-domain>
QUOTE_RETENTION_DAYS=30
```

API paleidimo komanda prieš Uvicorn automatiškai vykdo:

```text
alembic upgrade head
```

API loguose patikrinkite, kad migracija `0007` sėkmingai sukūrė
`ingestion_events` lentelę. Redis ingestion negalima įjungti anksčiau.

API turi turėti Railway public domain, pavyzdžiui:

```text
https://goldie-api-production.up.railway.app
```

## Web servisas

Railway nustatymai:

```text
Service name: web
Root Directory: /apps/web
Config File: /railway/web.toml
Replicas: 1
```

Kintamieji:

```text
NEXT_PUBLIC_API_URL=https://<api-public-domain>
NEXT_PUBLIC_WS_URL=wss://<api-public-domain>
```

Web servisas turi turėti atskirą Railway public domain. Po jo sukūrimo tikslų
Web adresą įrašykite į API `CORS_ORIGINS` ir redeployinkite API.

## Backtest worker servisas

Railway nustatymai:

```text
Service name: worker
Root Directory: repository root
Config File: /railway/worker.toml
Replicas: 1
```

Kintamieji:

```text
DATABASE_URL=<tas pats private PostgreSQL URL kaip API>
REDIS_URL=<tas pats private Redis URL kaip API>
```

Šis worker skirtas tik backtest užduotims.

## Ingestion worker servisas

Railway nustatymai:

```text
Service name: ingestion-worker
Root Directory: repository root
Config File: /railway/ingestion-worker.toml
Replicas: 1
```

Kintamieji:

```text
DATABASE_URL=<tas pats private PostgreSQL URL kaip API>
REDIS_URL=<tas pats private Redis URL kaip API>
INGESTION_CONSUMER_NAME=railway-ingestion-1
```

`INGESTION_CONSUMER_NAME` su viena replica nėra privalomas, bet rekomenduojamas.
Jeigu vėliau paleidžiamos kelios replicas, kiekviena privalo turėti unikalų
consumer vardą.

Worker naudoja:

```text
Stream: goldie:ingestion:v1
Consumer group: goldie-ingestion
Heartbeat key: goldie:ingestion-worker:heartbeat
```

## Market Data Collector servisas

Railway nustatymai:

```text
Service name: market-data-collector
Root Directory: repository root
Config File: /railway/collector.toml
Replicas: 1
```

Collector kintamieji:

```text
GOLDIE_API_URL=http://${{api.RAILWAY_PRIVATE_DOMAIN}}:${{api.PORT}}
GOLDIE_AGENT_TOKEN=<ta pati reikšmė kaip API AGENT_SERVICE_TOKEN>
GOLDIE_PROVIDER_ENVIRONMENT=practice
GOLDIE_INSTRUMENTS=EUR_USD,GBP_USD,USD_JPY,USD_CHF,USD_CAD,AUD_USD,NZD_USD,EUR_GBP,EUR_JPY,GBP_JPY
GOLDIE_QUOTE_INTERVAL_SECONDS=5
GOLDIE_CANDLE_POLL_SECONDS=15
GOLDIE_BACKFILL_DAYS=30
GOLDIE_BACKFILL_BATCH_SIZE=250
GOLDIE_REQUEST_TIMEOUT_SECONDS=60
GOLDIE_CONFIGURATION_RETRY_SECONDS=900
GOLDIE_OANDA_API_TOKEN=<OANDA practice token>
GOLDIE_OANDA_ACCOUNT_ID=<OANDA practice account ID>
GOLDIE_OANDA_REST_URL=https://api-fxpractice.oanda.com
GOLDIE_OANDA_STREAM_URL=https://stream-fxpractice.oanda.com

INGESTION_TRANSPORT=http
INGESTION_REDIS_URL=<Railway private Redis URL>
GOLDIE_QUOTE_BATCH_SECONDS=1
GOLDIE_QUOTE_BATCH_SIZE=250
GOLDIE_CANDLE_BATCH_SIZE=500
```

Pradinio diegimo metu privaloma palikti:

```text
INGESTION_TRANSPORT=http
```

`GOLDIE_API_URL` turi rodyti į API private domain, ne į Web servisą. Jeigu API
servisas pavadintas ne `api`, Railway autocomplete pasirinkite to serviso
`RAILWAY_PRIVATE_DOMAIN` ir `PORT`.

Vienas collector palaiko iki 20 instrumentų. Naudokite tik tuos instrumentus,
kuriems bus kuriami botai. Vienam feed rinkiniui laikykite vieną collector
replica, nes kelios replicas dubliuotų duomenų surinkimą.

### OANDA 403 diagnostika

Jeigu OANDA grąžina HTTP 403, patikrinkite:

1. Token ir account ID priklauso tam pačiam OANDA vartotojui.
2. Practice paskyra naudoja `api-fxpractice` ir `stream-fxpractice`.
3. Account matomas per OANDA `GET /v3/accounts`.
4. Account turi prieigą prie v20 API.

Jeigu `/v3/accounts` veikia, bet
`/v3/accounts/{accountID}/instruments` grąžina 403, perduokite collector loge
esantį OANDA `RequestID` adresu `api@oanda.com`.

## Maintenance servisas

Railway nustatymai:

```text
Service name: maintenance
Root Directory: repository root
Config File: /railway/maintenance.toml
Replicas: 1
```

Kintamieji:

```text
DATABASE_URL=<tas pats private PostgreSQL URL kaip API>
QUOTE_RETENTION_DAYS=30
```

`railway/maintenance.toml` suplanuoja servisą kasdien 02:15 UTC. Jis pašalina
senesnius nei 30 dienų quote įrašus. M1 žvakės išsaugomos.

## Diegimo seka

### 1. Sukurti infrastruktūrą

1. Sukurkite vieną Railway projektą ir production environment.
2. Pridėkite PostgreSQL servisą.
3. Pridėkite Redis servisą.
4. Patikrinkite, kad abu servisai yra pasiekiami per private networking.

### 2. Deployinti API

1. Sukurkite servisą iš Goldie GitHub repository.
2. Nustatykite pavadinimą `api`.
3. Nustatykite Config File `/railway/api.toml`.
4. Įrašykite API kintamuosius.
5. Sukurkite API public domain.
6. Paleiskite deploy.
7. Loguose patikrinkite `alembic upgrade head` ir migraciją `0007`.
8. Patikrinkite `GET /health/live`.
9. Patikrinkite `GET /health/ready`.

Abu health endpointai turi grąžinti HTTP 200 prieš tęsiant diegimą.

### 3. Deployinti Web

1. Sukurkite `web` servisą iš to paties repository.
2. Nustatykite Root Directory `/apps/web`.
3. Nustatykite Config File `/railway/web.toml`.
4. Įrašykite `NEXT_PUBLIC_API_URL` ir `NEXT_PUBLIC_WS_URL`.
5. Sukurkite Web public domain.
6. Įrašykite tikslų Web domain į API `CORS_ORIGINS`.
7. Redeployinkite API ir Web.
8. Patikrinkite prisijungimą per Web.

### 4. Deployinti Backtest Worker

1. Sukurkite `worker` servisą.
2. Nustatykite Config File `/railway/worker.toml`.
3. Prijunkite `DATABASE_URL` ir `REDIS_URL`.
4. Paleiskite vieną replica.
5. Loguose patikrinkite, kad worker prisijungė prie PostgreSQL ir Redis.

### 5. Deployinti Ingestion Worker

1. Sukurkite `ingestion-worker` servisą.
2. Nustatykite Config File `/railway/ingestion-worker.toml`.
3. Prijunkite `DATABASE_URL` ir `REDIS_URL`.
4. Nustatykite `INGESTION_CONSUMER_NAME`.
5. Paleiskite vieną replica.
6. Patikrinkite, kad worker sukūrė arba prisijungė prie
   `goldie-ingestion` consumer group.
7. Patikrinkite, kad atnaujinamas
   `goldie:ingestion-worker:heartbeat`.

Collector šiuo metu dar neturi būti perjungtas į Redis.

### 6. Deployinti Collector HTTP režimu

1. Sukurkite `market-data-collector` servisą.
2. Nustatykite Config File `/railway/collector.toml`.
3. Įrašykite OANDA ir Goldie collector kintamuosius.
4. Palikite `INGESTION_TRANSPORT=http`.
5. Paleiskite vieną replica.
6. Patikrinkite collector registraciją ir heartbeat `/collector` puslapyje.
7. Patikrinkite, kad quotes atkeliauja maždaug kas 5 sekundes.
8. Patikrinkite, kad saugomos tik užbaigtos M1 žvakės.
9. Sukurkite arba aktyvuokite SHADOW/PAPER botą.
10. Patikrinkite, kad generuojami signalai ir PAPER pozicijos.
11. Perkraukite collector ir patikrinkite, kad backfill nesukuria dublikatų.

Redis transportą įjunkite tik tada, kai visas šis etapas veikia.

### 7. Perjungti Collector į Redis

Collector Railway Variables pakeiskite:

```text
INGESTION_TRANSPORT=redis
```

Tada redeployinkite tik `market-data-collector`.

Po perjungimo patikrinkite:

1. Collector loguose nėra Redis publish klaidų.
2. `goldie:ingestion:v1` gauna naujus įvykius.
3. `ingestion-worker` skaito įvykius per `goldie-ingestion`.
4. Po sėkmingo PostgreSQL commit įvykiai yra patvirtinami su `XACK`.
5. Pending įvykių kiekis nuolat neauga.
6. Quotes ir candles toliau įrašomi į PostgreSQL.
7. Shadow signalų ir PAPER pozicijų rezultatai nepasikeitė.
8. `/collector` dashboard atsinaujina per Redis Pub/Sub.

### 8. Deployinti Maintenance

1. Sukurkite `maintenance` servisą.
2. Nustatykite Config File `/railway/maintenance.toml`.
3. Prijunkite `DATABASE_URL`.
4. Nustatykite `QUOTE_RETENTION_DAYS=30`.
5. Patikrinkite, kad Railway mato cron grafiką `15 2 * * *`.
6. Rankiniu deploy patikrinkite, kad maintenance komanda baigiasi sėkmingai.

## Priėmimo patikros

### Funkcinės patikros

1. `/health/live` grąžina HTTP 200.
2. `/health/ready` grąžina HTTP 200 ir DB ready būseną.
3. Prisijungimas per Web veikia.
4. Collector heartbeat yra `ONLINE` arba `MARKET_CLOSED`.
5. Quotes ir užbaigtos M1 žvakės saugomos PostgreSQL.
6. Pakartotas `event_id` nesukuria dublikatų.
7. SHADOW botas generuoja teorinius signalus.
8. PAPER botas turi atskirą 10 000 USD Goldie sąskaitą.
9. Backtest užduotis pasiekia galutinę būseną.
10. Backtest vykdymas nestabdo ingestion worker.

### Našumo patikros

1. `/health/live` ingestion metu atsako greičiau nei per 250 ms.
2. Nekache'intas `/api/v1/collector/overview` atsako greičiau nei per 3 s.
3. Cache'intas overview atsako greičiau nei per 500 ms.
4. Po Redis perjungimo overview p95 yra mažesnis nei 1 s.
5. `/collector` puslapio karkasas pasirodo greičiau nei per 1 s.

Overview našumą matuokite autentifikuota API užklausa. Vien naršyklės puslapio
užkrovimo laikas neatskiria API, cache ir frontend trukmės.

## Rollback į HTTP

Jeigu Redis ingestion neveikia stabiliai:

1. Collector Variables pakeiskite į:

```text
INGESTION_TRANSPORT=http
```

2. Redeployinkite tik `market-data-collector`.
3. Palikite ingestion worker veikiantį, kol jis apdoros jau esančius pending
   įvykius.
4. Patikrinkite, kad HTTP ingestion vėl rašo duomenis į PostgreSQL.
5. Patikrinkite `/collector` overview ir Shadow/Paper signalus.

Rollback metu netrinkite Redis Stream ar consumer group. Juose gali būti dar
neapdorotų įvykių.

## Servisų plėtimas

Redis Pub/Sub leidžia naudoti kelias API replicas, tačiau pirmiausia reikia
įvertinti PostgreSQL connection pool ir bendrą DB apkrovą.

Backtest workeriai gali būti plečiami horizontaliai, nes užduotys atominiu būdu
paimamos PostgreSQL. Ingestion workeriai gali būti plečiami per Redis consumer
group, bet kiekvienas turi turėti unikalų consumer vardą.

Collector laikykite po vieną replica vienam feed rinkiniui, kol nėra įdiegta
collector lyderystė.
