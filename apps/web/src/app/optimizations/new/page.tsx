"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useQueries, useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type {
  Bot,
  ConfigVersion,
  MarketFeed,
  OptimizationRun,
  StrategyMetadata,
} from "@/lib/types";
import { optimizationProfiles, type OptimizationProfileKey } from "./profiles";
import { defaultConfigId, getEligibleConfigs, runButtonLabel } from "./selection";

function inputDate(daysAgo: number): string {
  const value = new Date(Date.now() - daysAgo * 86400000);
  value.setSeconds(0, 0);
  return value.toISOString().slice(0, 16);
}

function profileDate(value: string): string {
  return `${value}T00:00`;
}

function optimizationPeriodDays(from: string, to: string): number {
  return (new Date(to).getTime() - new Date(from).getTime()) / 86400000;
}

export default function NewOptimizationPage() {
  const router = useRouter();
  const [profileKey, setProfileKey] = useState<OptimizationProfileKey>("realistic");
  const [selectedBotIds, setSelectedBotIds] = useState<string[]>([]);
  const [botSearch, setBotSearch] = useState("");
  const [configIds, setConfigIds] = useState<Record<string, string>>({});
  const [dateFrom, setDateFrom] = useState(profileDate("2023-01-01"));
  const [dateTo, setDateTo] = useState(profileDate("2025-01-01"));
  const [trialCount, setTrialCount] = useState("100");
  const [initialCapital, setInitialCapital] = useState("10000");
  const [fillMode, setFillMode] = useState<"perfect" | "simulated">("simulated");
  const [feeMaker, setFeeMaker] = useState("0.0002");
  const [feeTaker, setFeeTaker] = useState("0.0006");
  const [takerSlippage, setTakerSlippage] = useState("0.0005");
  const [slippageSmall, setSlippageSmall] = useState("0.0002");
  const [slippageMedium, setSlippageMedium] = useState("0.001");
  const [impactModel, setImpactModel] = useState("sqrt");
  const [modelSqrtLimit, setModelSqrtLimit] = useState("1.0");
  const [limitFillTimeout, setLimitFillTimeout] = useState("5");
  const [minQtyThreshold, setMinQtyThreshold] = useState("0.01");
  const [minQtyCheck, setMinQtyCheck] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const bots = useQuery({ queryKey: ["bots"], queryFn: () => api<Bot[]>("/api/v1/bots") });
  const feeds = useQuery({
    queryKey: ["market-feeds"],
    queryFn: () => api<MarketFeed[]>("/api/v1/market-feeds"),
  });
  const strategies = useQuery({
    queryKey: ["strategies"],
    queryFn: () => api<StrategyMetadata[]>("/api/v1/strategies"),
  });
  const configQueries = useQueries({
    queries: selectedBotIds.map((selectedBotId) => ({
      queryKey: ["bot-configs", selectedBotId],
      queryFn: () => api<ConfigVersion[]>(`/api/v1/bots/${selectedBotId}/config-versions`),
    })),
  });
  const selectedBots = (bots.data ?? []).filter((bot) => selectedBotIds.includes(bot.id));
  const normalizedBotSearch = botSearch.trim().toLocaleLowerCase();
  const filteredBots = (bots.data ?? []).filter((bot) => {
    if (!normalizedBotSearch) return true;
    const feed = feeds.data?.find((item) => item.id === bot.market_feed_id);
    return bot.name.toLocaleLowerCase().includes(normalizedBotSearch)
      || feed?.provider_symbol.toLocaleLowerCase().includes(normalizedBotSearch);
  });
  const configsByBot = new Map(
    selectedBotIds.map((selectedBotId, index) => [selectedBotId, configQueries[index]?.data ?? []]),
  );
  const botSelections = selectedBots.map((bot) => {
    const eligibleConfigs = getEligibleConfigs(configsByBot.get(bot.id) ?? []);
    const configId = configIds[bot.id] ?? defaultConfigId(bot, eligibleConfigs);
    return {
      bot,
      configId,
      config: eligibleConfigs.find((item) => item.id === configId),
      eligibleConfigs,
      feed: feeds.data?.find((feed) => feed.id === bot.market_feed_id),
    };
  });
  const selectedParameters = (() => {
    const names = new Set<string>();
    for (const selection of botSelections) {
      const strategy = strategies.data?.find(
        (item) => item.name === selection.config?.config.strategy.name,
      );
      Object.keys(strategy?.parameters ?? {}).forEach((name) => names.add(name));
    }
    return [...names];
  })();
  const configsLoading = configQueries.some((query) => query.isLoading);
  const invalidSelection = botSelections.some(
    ({ bot, configId }) => !bot.market_feed_id || !configId,
  );
  const selectedProfile = optimizationProfiles.find((item) => item.key === profileKey);
  const customProfile = profileKey === "other";

  useEffect(() => {
    if (!selectedProfile || selectedProfile.key === "other") return;
    const [from, to] = selectedProfile.fromTo.split(":");
    setDateFrom(profileDate(from));
    setDateTo(profileDate(to));
    setTrialCount(selectedProfile.trials);
    setInitialCapital(selectedProfile.initialCapital);
    setFillMode(selectedProfile.fill === "perfect" ? "perfect" : "simulated");
    setFeeMaker(selectedProfile.feeMaker);
    setFeeTaker(selectedProfile.feeTaker);
    setTakerSlippage(selectedProfile.takerSlippage);
    setSlippageSmall(selectedProfile.slippageSmall);
    setSlippageMedium(selectedProfile.slippageMedium);
    setImpactModel("sqrt");
    setModelSqrtLimit(selectedProfile.modelSqrtLimit);
    setLimitFillTimeout(selectedProfile.limitFillTimeout);
    setMinQtyThreshold(selectedProfile.minQtyThreshold);
    setMinQtyCheck(selectedProfile.minQtyCheck);
  }, [selectedProfile]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!botSelections.length) {
      setError("Select at least one bot.");
      return;
    }
    if (invalidSelection) {
      setError("Every selected bot needs a market feed and a validated configuration.");
      return;
    }
    if (optimizationPeriodDays(dateFrom, dateTo) > 365) {
      setError("Optimization period cannot exceed 365 days.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const results = await Promise.allSettled(
        botSelections.map(({ bot, configId }) =>
          api<OptimizationRun>("/api/v1/optimizations", {
            method: "POST",
            body: JSON.stringify({
              bot_id: bot.id,
              config_version_id: configId,
              market_feed_id: bot.market_feed_id,
              date_from: new Date(dateFrom).toISOString(),
              date_to: new Date(dateTo).toISOString(),
              n_trials: Number(trialCount),
              objective: "BALANCED",
              initial_capital: initialCapital,
              fill_mode: fillMode,
              fee_maker: feeMaker,
              fee_taker: feeTaker,
              taker_slippage: takerSlippage,
              slippage_small: slippageSmall,
              slippage_medium: slippageMedium,
              medium_impact: slippageMedium,
              impact_model: impactModel,
              model_sqrt_limit: modelSqrtLimit,
              limit_fill_timeout_s: Number(limitFillTimeout),
              min_qty_threshold: minQtyThreshold,
              min_qty_check: minQtyCheck,
            }),
          }),
        ),
      );
      const created = results.flatMap((result) => result.status === "fulfilled" ? [result.value] : []);
      const failedBotIds = results.flatMap((result, index) =>
        result.status === "rejected" ? [botSelections[index].bot.id] : [],
      );
      if (failedBotIds.length) {
        setSelectedBotIds(failedBotIds);
        setError(`${created.length} of ${results.length} optimizations queued. ${failedBotIds.length} failed; retry the remaining selection.`);
        return;
      }
      router.push(created.length === 1 ? `/optimizations/${created[0].id}` : "/optimizations");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section>
      <header className="page-header">
        <div>
          <span className="eyebrow">NEW SEARCH</span>
          <h1>Run optimization</h1>
          <p>
            Choose an optimization profile. Only strategy parameters are searched;
            filters, session, trade model, and costs stay fixed.
          </p>
        </div>
      </header>
      <form className="panel form-grid optimization-form" onSubmit={submit}>
        <div className="optimization-form-columns">
          <div className="optimization-form-column">
        <div id="profile-picker" className="profile-picker">
          {optimizationProfiles.map((profile) => (
            <button
              key={profile.key}
              type="button"
              className={`profile-option${profile.key === profileKey ? " selected" : ""}`}
              onClick={() => {
                setProfileKey(profile.key);
                if (profile.key === "other") {
                  setDateFrom(inputDate(30));
                  setDateTo(inputDate(0));
                  setTrialCount(profile.trials);
                  setInitialCapital(profile.initialCapital);
                  setFillMode("simulated");
                  setFeeMaker(profile.feeMaker);
                  setFeeTaker(profile.feeTaker);
                  setTakerSlippage("0");
                  setSlippageSmall(profile.slippageSmall);
                  setSlippageMedium(profile.slippageMedium);
                  setImpactModel("sqrt");
                  setModelSqrtLimit("1.0");
                  setLimitFillTimeout(profile.limitFillTimeout);
                  setMinQtyThreshold("0");
                  setMinQtyCheck(profile.minQtyCheck);
                }
              }}
            >
              <strong>{profile.title}</strong>
              <span>{profile.subtitle}</span>
            </button>
          ))}
        </div>
        {selectedProfile && !customProfile && (
          <div id="profile-panel" className="panel">
            <h2>{selectedProfile.title} profile</h2>
            <div className="key-values">
              <div><dt>FromTo</dt><dd>{selectedProfile.fromTo}</dd></div>
              <div><dt>Trials</dt><dd>{selectedProfile.trials}</dd></div>
              <div><dt>Initial capital</dt><dd>{selectedProfile.initialCapital}</dd></div>
              <div><dt>makerFee</dt><dd>{selectedProfile.feeMaker}</dd></div>
              <div><dt>takerFee</dt><dd>{selectedProfile.feeTaker}</dd></div>
              <div><dt>takerSlippage</dt><dd>{selectedProfile.takerSlippage}</dd></div>
              <div><dt>smallSlippage</dt><dd>{selectedProfile.slippageSmall}</dd></div>
              <div><dt>mediumImpact</dt><dd>{selectedProfile.slippageMedium}</dd></div>
              <div><dt>modelsqrtLimit</dt><dd>{selectedProfile.modelSqrtLimit}</dd></div>
              <div><dt>fill</dt><dd>{selectedProfile.fill}</dd></div>
              <div><dt>timeout_s</dt><dd>{selectedProfile.limitFillTimeout}</dd></div>
              <div><dt>Min_qty_check</dt><dd>{selectedProfile.minQtyThreshold}</dd></div>
              <div><dt>check</dt><dd>{String(selectedProfile.minQtyCheck)}</dd></div>
            </div>
          </div>
        )}
        {customProfile && <div id="profile-panel" className="panel compact-form form-grid">
          <label>
            From
            <input
              required
              type="datetime-local"
              value={dateFrom}
              onChange={(event) => setDateFrom(event.target.value)}
            />
          </label>
          <label>
            To
            <input
              required
              type="datetime-local"
              value={dateTo}
              onChange={(event) => setDateTo(event.target.value)}
            />
          </label>
          <label>
            Trials
            <input
              required
              type="number"
              min="1"
              max="500"
              step="1"
              value={trialCount}
              onChange={(event) => setTrialCount(event.target.value)}
            />
          </label>
          <label>
            Initial capital
            <input
              required
              type="number"
              min="1"
              step="0.01"
              value={initialCapital}
              onChange={(event) => setInitialCapital(event.target.value)}
            />
          </label>
          <label>
            Fee maker
            <input
              required
              type="number"
              min="0"
              step="0.0001"
              value={feeMaker}
              onChange={(event) => setFeeMaker(event.target.value)}
            />
          </label>
          <label>
            Fee taker
            <input
              required
              type="number"
              min="0"
              step="0.0001"
              value={feeTaker}
              onChange={(event) => setFeeTaker(event.target.value)}
            />
          </label>
          <label>
            Fill
            <select value={fillMode} onChange={(event) => setFillMode(event.target.value as "perfect" | "simulated")}>
              <option value="perfect">perfect</option>
              <option value="simulated">simulated</option>
            </select>
          </label>
          <label>
            Taker slippage
            <input
              required
              type="number"
              min="0"
              step="0.0001"
              value={takerSlippage}
              onChange={(event) => setTakerSlippage(event.target.value)}
            />
          </label>
          <label>
            Slippage small
            <input
              required
              type="number"
              min="0"
              step="0.0001"
              value={slippageSmall}
              onChange={(event) => setSlippageSmall(event.target.value)}
            />
          </label>
          <label>
            Medium impact
            <input
              required
              type="number"
              min="0"
              step="0.0001"
              value={slippageMedium}
              onChange={(event) => setSlippageMedium(event.target.value)}
            />
          </label>
          <label>
            Impact model
            <select value={impactModel} onChange={(event) => setImpactModel(event.target.value)}>
              <option value="sqrt">sqrt</option>
            </select>
          </label>
          <label>
            Model sqrt limit
            <input
              required
              type="number"
              min="0"
              step="0.1"
              value={modelSqrtLimit}
              onChange={(event) => setModelSqrtLimit(event.target.value)}
            />
          </label>
          <label>
            Limit fill timeout (s)
            <input
              required
              type="number"
              min="0"
              step="1"
              value={limitFillTimeout}
              onChange={(event) => setLimitFillTimeout(event.target.value)}
            />
          </label>
          <label>
            Min qty threshold
            <input
              required
              type="number"
              min="0"
              step="0.01"
              value={minQtyThreshold}
              onChange={(event) => setMinQtyThreshold(event.target.value)}
            />
          </label>
          <label className="checkbox-field">
            Min qty check
            <input
              type="checkbox"
              checked={minQtyCheck}
              onChange={(event) => setMinQtyCheck(event.target.checked)}
            />
          </label>
        </div>}
        <div id="search-scope" className="panel">
          <h2>Search scope</h2>
          <p className="muted">Strategy parameters included in this optimization run.</p>
          {!selectedParameters.length ? (
            <p className="muted">
              Choose bots with validated strategy configurations to preview searchable
              parameters.
            </p>
          ) : (
            <div className="key-values">
              {selectedParameters.map((name) => (
                <div key={name}>
                  <dt>{name}</dt>
                  <dd>Included in selected strategies</dd>
                </div>
              ))}
            </div>
          )}
        </div>
          </div>
          <div className="optimization-form-column">
            <div id="bot-picker" className="panel optimization-bot-picker">
              <div className="selection-heading">
                <div>
                  <h2>Bots</h2>
                  <p className="muted">Select every bot that should receive an optimization run.</p>
                </div>
                <div className="button-row">
                  <button
                    type="button"
                    className="button button-ghost"
                    disabled={!bots.data?.length}
                    onClick={() => setSelectedBotIds(
                      (bots.data ?? []).filter((bot) => bot.market_feed_id).map((bot) => bot.id),
                    )}
                  >
                    Select all
                  </button>
                  <button
                    type="button"
                    className="button button-ghost"
                    disabled={!selectedBotIds.length}
                    onClick={() => setSelectedBotIds([])}
                  >
                    Clear
                  </button>
                </div>
              </div>
              <label className="optimization-bot-search">
                Search bot
                <input
                  type="search"
                  placeholder="Name or market symbol..."
                  value={botSearch}
                  onChange={(event) => setBotSearch(event.target.value)}
                />
              </label>
              {bots.isLoading && <span className="muted">Loading bots...</span>}
              {!bots.isLoading && !bots.data?.length && <span className="muted">No bots available.</span>}
              {!bots.isLoading && !!bots.data?.length && !filteredBots.length && (
                <span className="muted">No bots match this search.</span>
              )}
              <div className="selection-list optimization-bot-list">
                {filteredBots.map((bot) => {
                  const feed = feeds.data?.find((item) => item.id === bot.market_feed_id);
                  return (
                    <label className="checkbox-row bulk-option" key={bot.id}>
                      <input
                        type="checkbox"
                        disabled={!bot.market_feed_id}
                        checked={selectedBotIds.includes(bot.id)}
                        onChange={(event) => setSelectedBotIds((current) =>
                          event.target.checked
                            ? [...new Set([...current, bot.id])]
                            : current.filter((item) => item !== bot.id),
                        )}
                      />
                      <span>
                        <strong>{bot.name}</strong>
                        <small>{feed?.provider_symbol ?? "No market feed — unavailable"}</small>
                      </span>
                    </label>
                  );
                })}
              </div>
            </div>
            {!!botSelections.length && (
              <div id="config-panel" className="panel optimization-config-panel">
                <div className="section-title">
                  <div>
                    <h2>Configurations</h2>
                    <p>{botSelections.length} bot(s) selected. Choose a validated version for each.</p>
                  </div>
                  <span className="status">Objective: BALANCED</span>
                </div>
                <div className="optimization-config-list">
                  {botSelections.map(({ bot, configId, eligibleConfigs, feed }) => (
                    <div className="optimization-config-row" key={bot.id}>
                      <div>
                        <strong>{bot.name}</strong>
                        <small>{feed?.provider_symbol ?? "No market feed"}</small>
                      </div>
                      <label>
                        Configuration version
                        <select
                          required
                          value={configId}
                          onChange={(event) => setConfigIds((current) => ({
                            ...current,
                            [bot.id]: event.target.value,
                          }))}
                        >
                          <option value="">Select validated configuration</option>
                          {eligibleConfigs.map((item) => (
                            <option key={item.id} value={item.id}>
                              Version {item.version} - {item.status}
                            </option>
                          ))}
                        </select>
                      </label>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
        {error && <div className="error-box">{error}</div>}
        <div className="button-row optimization-form-actions">
          <button
            type="button"
            className="button button-secondary"
            onClick={() => router.back()}
          >
            Cancel
          </button>
          <button
            className="button button-primary"
            disabled={busy || configsLoading || !botSelections.length || invalidSelection}
          >
            {busy
              ? `Queueing ${botSelections.length} optimization(s)...`
              : runButtonLabel(botSelections.length)}
          </button>
        </div>
      </form>
    </section>
  );
}
