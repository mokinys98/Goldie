"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Bot, MarketFeed, StrategyProfile } from "@/lib/types";

export default function NewBotPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [marketFeedId, setMarketFeedId] = useState("");
  const [strategyProfileId, setStrategyProfileId] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const feeds = useQuery({
    queryKey: ["market-feeds"],
    queryFn: () => api<MarketFeed[]>("/api/v1/market-feeds"),
  });
  const strategies = useQuery({
    queryKey: ["strategy-profiles"],
    queryFn: () => api<StrategyProfile[]>("/api/v1/strategy-profiles"),
  });

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const bot = await api<Bot>("/api/v1/bots", {
        method: "POST",
        body: JSON.stringify({
          name,
          description,
          mode: "SHADOW",
          market_feed_id: marketFeedId || null,
          strategy_profile_id: strategyProfileId,
        }),
      });
      router.push(`/bots/${bot.id}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not create bot");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="narrow-page">
      <header className="page-header">
        <div>
          <span className="eyebrow">NEW INSTANCE</span>
          <h1>Create bot</h1>
          <p>A bot with a market feed starts monitoring immediately.</p>
        </div>
      </header>
      <form className="panel form-grid" onSubmit={submit}>
        <label>
          Name
          <input
            required
            minLength={2}
            maxLength={120}
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="EURUSD M1 Shadow"
          />
        </label>
        <label>
          Description
          <textarea
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder="Purpose of this bot instance"
          />
        </label>
        <label>
          Global strategy
          <select
            required
            value={strategyProfileId}
            onChange={(event) => setStrategyProfileId(event.target.value)}
          >
            <option value="">Select strategy</option>
            {(strategies.data ?? []).map((strategy) => (
              <option key={strategy.id} value={strategy.id}>{strategy.name}</option>
            ))}
          </select>
        </label>
        <label>
          Market feed
          <select
            value={marketFeedId}
            onChange={(event) => setMarketFeedId(event.target.value)}
          >
            <option value="">No feed yet</option>
            {(feeds.data ?? []).map((feed) => (
              <option key={feed.id} value={feed.id}>
                {feed.canonical_symbol} · {feed.provider} · {feed.status}
              </option>
            ))}
          </select>
        </label>
        <label>
          Mode
          <input value="SHADOW" disabled />
        </label>
        {feeds.isError && (
          <div className="error-box">Could not load available market feeds.</div>
        )}
        {strategies.isError && (
          <div className="error-box">Could not load available strategies.</div>
        )}
        {error && <div className="error-box">{error}</div>}
        <div className="button-row">
          <button
            type="button"
            className="button button-secondary"
            onClick={() => router.back()}
          >
            Cancel
          </button>
          <button className="button button-primary" disabled={busy}>
            {busy ? "Creating..." : "Create bot"}
          </button>
        </div>
      </form>
    </section>
  );
}
