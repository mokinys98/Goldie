# Optuna optimization workflow

Šis dokumentas aprašo, kaip paleisti ir deployinti Goldie strategijos
parametrų optimizaciją su atskiru `optuna-worker`.

## Paskirtis

Optimizacija v1:

- optimizuoja tik `config.strategy.parameters`;
- naudoja tą patį Goldie deterministinį M1 backtest engine kaip ir paprasti
  backtestai;
- palieka `filters`, `session`, `theoretical_trade` ir cost model laukus
  fiksuotus iš pasirinkto `config_snapshot`;
- saugo run ir trial būseną PostgreSQL;
- naudoja Redis tik job pažadinimui ir heartbeat.

## Lokalūs žingsniai

1. Sinchronizuok Python paketus:

   ```powershell
   uv sync --all-packages
   ```

2. Paleisk lokalią platformą:

   ```powershell
   docker compose -f infrastructure/docker/compose.yml --env-file .env up --build
   ```

3. Atskirame terminale paleisk paprastą backtest worker:

   ```powershell
   uv run --package goldie-worker python -m goldie_worker
   ```

4. Atskirame terminale paleisk Optuna worker:

   ```powershell
   uv run --package goldie-optuna-worker python -m goldie_optuna_worker
   ```

5. Atidaryk `http://localhost:3000`, prisijunk ir eik į `Optimization`.

## UI naudojimas

1. Pasirink botą su priskirtu market feed.
2. Pasirink `ACTIVE`, `VALIDATED` arba `SUPERSEDED` config version.
3. Pasirink datų intervalą.
4. Nurodyk `n_trials`.
5. Palik `BALANCED` objective.
6. Paleisk optimization run.

`BALANCED` objective nėra “best settings” selektorius vien pagal PnL.
Jis baudžia drawdown ir per mažą trade sample:

```text
BALANCED = net_pnl - 1.5 * max_drawdown - 50 * missing_trades_below_30
no-trade trials score = -99999
```

Tai reiškia, kad 1-2 sandorių kandidatai neturi būti interpretuojami kaip
robustūs laimėtojai, net jei jie atsiduria viršuje dėl to, kad kiti kandidatai
prekiavo dar blogiau.

Optimization detail puslapyje turi matytis:

- run būsena;
- trial progresas;
- `best_candidate.score`;
- `best_candidate.sampled_parameters`;
- `summary.research_quality_gates`;
- top trial lentelė.

## Railway diegimas

Naudok tą patį Railway projektą kaip ir likusi Goldie infrastruktūra.

Pridėk papildomą servisą:

```text
Service name: optuna-worker
Root Directory: repository root
Config File: /railway/optuna-worker.toml
Replicas: 1
DATABASE_URL=<tas pats private PostgreSQL URL kaip API>
REDIS_URL=<tas pats private Redis URL kaip API>
```

Rekomenduojama diegimo seka:

1. Deployinti `api`.
2. Deployinti `web`.
3. Deployinti `worker`.
4. Deployinti `optuna-worker`.
5. Sukurti vieną testinį optimization run iš UI.
6. Patikrinti, kad `optuna-worker` loguose matosi run pickup ir trial vykdymas.

## Railway acceptance checks

Patikrink:

1. `optuna-worker` sėkmingai startuoja.
2. Redis heartbeat raktas `goldie:optuna-worker:heartbeat` atsinaujina.
3. UI sukurtas optimization run pereina iš `PENDING` į `RUNNING`.
4. PostgreSQL atsiranda `optimization_runs` ir `optimization_trials` įrašai.
5. Run pasiekia `SUCCEEDED`, `FAILED` arba `CANCELLED`.
6. `best_candidate` ir `top_candidates` yra užpildyti bent vienam sėkmingam run.

## V1 ribos

- Nėra automatinio geriausių parametrų perkėlimo į aktyvią boto konfigūraciją.
- Nėra custom objective builder UI.
- Nėra walk-forward orchestracijos.
- Vienas study nėra skaidomas tarp kelių worker procesų.
