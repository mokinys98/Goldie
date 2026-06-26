"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { CollectorProviderInstruments } from "@/lib/types";

const providers = [
  { value: "binance_spot", label: "Binance Spot" },
  { value: "oanda", label: "OANDA" },
];

export default function NewCollectorInstrumentPage() {
  const router = useRouter();
  const [provider, setProvider] = useState("binance_spot");
  const [providerSymbol, setProviderSymbol] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const instruments = useQuery({
    queryKey: ["collector-provider-instruments", provider],
    queryFn: () =>
      api<CollectorProviderInstruments>(
        `/api/v1/collector/provider-instruments?provider=${encodeURIComponent(provider)}`,
      ),
  });

  const options = useMemo(
    () => instruments.data?.instruments ?? [],
    [instruments.data?.instruments],
  );

  useEffect(() => {
    setProviderSymbol(options[0]?.provider_symbol ?? "");
  }, [options]);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!providerSymbol) return;
    setError("");
    setBusy(true);
    try {
      await api("/api/v1/collector/instruments", {
        method: "POST",
        body: JSON.stringify({
          provider,
          environment:
            instruments.data?.environment
            ?? (provider === "binance_spot" ? "spot" : "practice"),
          provider_symbol: providerSymbol,
        }),
      });
      router.push("/collector");
      router.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not add instrument");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="narrow-page">
      <header className="page-header">
        <div>
          <span className="eyebrow">MARKET DATA CONTROL</span>
          <h1>Add instrument</h1>
          <p>Select the provider first, then choose an available pair returned by that provider.</p>
        </div>
        <Link className="button button-secondary" href="/collector">Back</Link>
      </header>

      {(error || instruments.error) && (
        <div className="error-box collector-alert">
          {error || instruments.error?.message || "Provider instruments unavailable"}
        </div>
      )}

      <form className="panel form-grid" onSubmit={submit}>
        <label>
          Provider
          <select
            value={provider}
            onChange={(event) => setProvider(event.target.value)}
          >
            {providers.map((item) => (
              <option key={item.value} value={item.value}>{item.label}</option>
            ))}
          </select>
        </label>

        <label>
          Pair
          <select
            aria-label="Provider pair"
            disabled={instruments.isLoading || !options.length}
            value={providerSymbol}
            onChange={(event) => setProviderSymbol(event.target.value)}
          >
            {instruments.isLoading ? (
              <option value="">Loading pairs...</option>
            ) : options.length ? (
              options.map((item) => (
                <option key={item.provider_symbol} value={item.provider_symbol}>
                  {item.provider_symbol} - {item.display_name}
                </option>
              ))
            ) : (
              <option value="">No pairs available</option>
            )}
          </select>
        </label>

        <label>
          Environment
          <input disabled value={instruments.data?.environment ?? "--"} />
        </label>

        <div className="button-row">
          <button
            className="button button-primary"
            disabled={busy || instruments.isLoading || !providerSymbol}
          >
            {busy ? "Adding..." : "Add instrument"}
          </button>
          <Link className="button button-secondary" href="/collector">Cancel</Link>
        </div>
      </form>
    </section>
  );
}
