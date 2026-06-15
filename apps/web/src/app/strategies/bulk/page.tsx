"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type {
  BulkBotResult,
  MarketFeed,
  StrategyProfile,
} from "@/lib/types";
import { StatusPill } from "@/components/status-pill";

type CombinationResult = BulkBotResult & {
  strategyId: string;
  strategyName: string;
};

export default function BulkBotsCreationPage() {
  const client = useQueryClient();
  const [selectedStrategies, setSelectedStrategies] = useState<string[]>([]);
  const [selectedFeeds, setSelectedFeeds] = useState<string[]>([]);
  const [mode, setMode] = useState<"SHADOW" | "PAPER">("SHADOW");
  const [template, setTemplate] = useState("{symbol}-{strategy}-{mode}");
  const [results, setResults] = useState<CombinationResult[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const strategies = useQuery({
    queryKey: ["strategy-profiles"],
    queryFn: () => api<StrategyProfile[]>("/api/v1/strategy-profiles"),
  });
  const feeds = useQuery({
    queryKey: ["market-feeds"],
    queryFn: () => api<MarketFeed[]>("/api/v1/market-feeds"),
  });

  const selectedStrategyRows = (strategies.data ?? []).filter((strategy) =>
    selectedStrategies.includes(strategy.id)
  );
  const selectedFeedRows = (feeds.data ?? []).filter((feed) =>
    selectedFeeds.includes(feed.id)
  );
  const combinationCount = selectedStrategyRows.length * selectedFeedRows.length;
  const previews = useMemo(
    () =>
      selectedStrategyRows.flatMap((strategy) =>
        selectedFeedRows.map((feed) => ({
          key: `${strategy.id}:${feed.id}`,
          strategy: strategy.name,
          symbol: feed.canonical_symbol,
          name: generateBotName(template, strategy.name, feed.canonical_symbol, mode),
        }))
      ),
    [mode, selectedFeedRows, selectedStrategyRows, template],
  );

  const toggle = (
    value: string,
    checked: boolean,
    setter: React.Dispatch<React.SetStateAction<string[]>>,
  ) => {
    setter((current) =>
      checked ? [...new Set([...current, value])] : current.filter((item) => item !== value)
    );
  };

  const createBots = async () => {
    if (!combinationCount) return;
    setBusy(true);
    setError("");
    setResults([]);
    try {
      const batches = await Promise.all(
        selectedStrategyRows.map(async (strategy) => {
          const batch = await api<BulkBotResult[]>("/api/v1/bots/bulk", {
            method: "POST",
            body: JSON.stringify({
              request_id: crypto.randomUUID(),
              strategy_profile_id: strategy.id,
              market_feed_ids: selectedFeeds,
              mode,
              name_template: template,
            }),
          });
          return batch.map((result) => ({
            ...result,
            strategyId: strategy.id,
            strategyName: strategy.name,
          }));
        }),
      );
      setResults(batches.flat());
      await Promise.all([
        client.invalidateQueries({ queryKey: ["bots"] }),
        client.invalidateQueries({ queryKey: ["strategy-profiles"] }),
      ]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not create bots");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section>
      <header className="page-header">
        <div>
          <span className="eyebrow">BULK CREATION</span>
          <h1>Bulk bots creation</h1>
          <p>Select strategies and currency pairs. Every combination creates one bot.</p>
        </div>
        <Link className="button button-secondary" href="/strategies">Back to strategies</Link>
      </header>

      {(strategies.error || feeds.error) && (
        <div className="error-box">
          {strategies.error?.message ?? feeds.error?.message}
        </div>
      )}

      <div className="panel">
        <div className="bulk-selection-grid">
          <SelectionGroup
            title="1. Strategies"
            items={(strategies.data ?? []).map((strategy) => ({
              id: strategy.id,
              label: strategy.name,
              detail: strategy.config.strategy.name,
            }))}
            selected={selectedStrategies}
            loading={strategies.isLoading}
            onChange={(id, checked) => toggle(id, checked, setSelectedStrategies)}
            onSelectAll={() =>
              setSelectedStrategies((strategies.data ?? []).map((strategy) => strategy.id))
            }
            onClear={() => setSelectedStrategies([])}
          />
          <SelectionGroup
            title="2. Currency pairs"
            items={(feeds.data ?? []).map((feed) => ({
              id: feed.id,
              label: feed.canonical_symbol,
              detail: `${feed.provider} / ${feed.environment} / ${feed.status}`,
            }))}
            selected={selectedFeeds}
            loading={feeds.isLoading}
            onChange={(id, checked) => toggle(id, checked, setSelectedFeeds)}
            onSelectAll={() => setSelectedFeeds((feeds.data ?? []).map((feed) => feed.id))}
            onClear={() => setSelectedFeeds([])}
          />
          <div className="form-grid bulk-controls">
            <h3>3. Bot settings</h3>
            <label>
              Mode
              <select
                value={mode}
                onChange={(event) => setMode(event.target.value as "SHADOW" | "PAPER")}
              >
                <option value="SHADOW">SHADOW</option>
                <option value="PAPER">PAPER</option>
              </select>
            </label>
            <label>
              Name template
              <input value={template} onChange={(event) => setTemplate(event.target.value)} />
            </label>
            <p className="muted">
              Available values: {"{symbol}"}, {"{strategy}"}, {"{mode}"}
            </p>
            <div className="bulk-total">
              <span>Strategies</span><strong>{selectedStrategyRows.length}</strong>
              <span>Pairs</span><strong>{selectedFeedRows.length}</strong>
              <span>Total bots</span><strong>{combinationCount}</strong>
            </div>
          </div>
        </div>

        {!!previews.length && (
          <div className="table-wrap table-actions">
            <table>
              <thead>
                <tr><th>Strategy</th><th>Pair</th><th>Generated bot name</th></tr>
              </thead>
              <tbody>
                {previews.map((preview) => (
                  <tr key={preview.key}>
                    <td>{preview.strategy}</td>
                    <td>{preview.symbol}</td>
                    <td>{preview.name}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {error && <div className="error-box table-actions">{error}</div>}
        <div className="button-row table-actions">
          <button
            className="button button-primary"
            disabled={!combinationCount || busy}
            onClick={() => void createBots()}
          >
            {busy ? "Creating bots..." : `Create ${combinationCount} bot(s)`}
          </button>
        </div>
      </div>

      {!!results.length && <ResultsTable results={results} />}
    </section>
  );
}

function SelectionGroup({
  title,
  items,
  selected,
  loading,
  onChange,
  onSelectAll,
  onClear,
}: {
  title: string;
  items: Array<{ id: string; label: string; detail: string }>;
  selected: string[];
  loading: boolean;
  onChange: (id: string, checked: boolean) => void;
  onSelectAll: () => void;
  onClear: () => void;
}) {
  return (
    <div>
      <div className="selection-heading">
        <h3>{title}</h3>
        <div className="button-row">
          <button className="button button-ghost" disabled={!items.length} onClick={onSelectAll}>
            Select all
          </button>
          <button className="button button-ghost" disabled={!selected.length} onClick={onClear}>
            Clear
          </button>
        </div>
      </div>
      <div className="selection-list bulk-selection-list">
        {loading && <span className="muted">Loading...</span>}
        {!loading && !items.length && <span className="muted">No items available.</span>}
        {items.map((item) => (
          <label className="checkbox-row bulk-option" key={item.id}>
            <input
              type="checkbox"
              checked={selected.includes(item.id)}
              onChange={(event) => onChange(item.id, event.target.checked)}
            />
            <span><strong>{item.label}</strong><small>{item.detail}</small></span>
          </label>
        ))}
      </div>
    </div>
  );
}

function ResultsTable({ results }: { results: CombinationResult[] }) {
  const created = results.filter((result) => result.status === "CREATED").length;
  const existing = results.filter((result) => result.status === "EXISTS").length;
  const failed = results.filter((result) => result.status === "FAILED").length;
  return (
    <div className="panel strategy-editor-section">
      <div className="section-title">
        <div>
          <h2>Creation results</h2>
          <p>{created} created, {existing} already existed, {failed} failed.</p>
        </div>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr><th>Strategy</th><th>Name</th><th>Status</th><th>Result</th></tr>
          </thead>
          <tbody>
            {results.map((result) => (
              <tr key={`${result.strategyId}:${result.market_feed_id}`}>
                <td>{result.strategyName}</td>
                <td>
                  {result.bot ? (
                    <Link className="table-link" href={`/bots/${result.bot.id}`}>
                      {result.name}
                    </Link>
                  ) : result.name || "--"}
                </td>
                <td><StatusPill value={result.status} /></td>
                <td>{result.error ?? (result.status === "EXISTS" ? "Already exists" : "Created and activated")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function generateBotName(
  template: string,
  strategyName: string,
  symbol: string,
  mode: "SHADOW" | "PAPER",
) {
  return template
    .replaceAll("{symbol}", symbol)
    .replaceAll("{strategy}", strategyName.toLowerCase().replaceAll(" ", "-"))
    .replaceAll("{mode}", mode.toLowerCase());
}
