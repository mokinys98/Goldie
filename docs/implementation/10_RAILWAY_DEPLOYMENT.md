# Railway deployment

Goldie hosted shadow/paper etapas Railway platformoje naudoja:

- `web`;
- `api`;
- `market-data-collector`;
- PostgreSQL;
- kasdienį `maintenance` servisą.

Servisų konfigūracijos laikomos [`railway/`](../../railway/) kataloge. Pilnas
diegimo, kintamųjų ir priėmimo patikrų planas aprašytas
[`09_RAILWAY_HOSTED_SHADOW.md`](09_RAILWAY_HOSTED_SHADOW.md).

## Diegimo tvarka

1. Sukurti Railway PostgreSQL ir prijungti jo `DATABASE_URL` prie API bei
   maintenance servisų.
2. Paleisti API. Starto komanda prieš Uvicorn automatiškai vykdo
   `alembic upgrade head`.
3. Sukonfigūruoti Web build kintamuosius `NEXT_PUBLIC_API_URL` ir
   `NEXT_PUBLIC_WS_URL`, nustatyti Web serviso Root Directory į `/apps/web`,
   Config File į `/railway/web.toml`, tada paleisti Web.
4. Collector servise nustatyti OANDA practice credentials, vidinį API URL ir
   bendrą `AGENT_SERVICE_TOKEN`.
5. Paleisti collector tik po sėkmingo API `/health/ready` patikrinimo.
6. Maintenance servisą suplanuoti kartą per dieną.

Collector naudoja OANDA tik rinkos duomenims. Jis neturi orderių ar sąskaitos
balanso importavimo sąsajų.

## Priėmimas

1. `/health/live` grąžina `status=ok`.
2. `/health/ready` grąžina `database=ok`.
3. Collector heartbeat matomas kaip `ONLINE` arba `MARKET_CLOSED`.
4. Quotes atkeliauja maždaug kas 5 sekundes, o M1 saugomos tik užbaigtos.
5. Du botai gali naudoti tą patį feed nedubliuojant rinkos duomenų.
6. PAPER botas turi atskirą 10 000 USD Goldie sąskaitą.
7. Shadow performance rodoma kaip teorinė ir nevykdo brokerio pavedimų.
