"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { Bot } from "@/lib/types";

export default function NewBotPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const bot = await api<Bot>("/api/v1/bots", {
        method: "POST",
        body: JSON.stringify({ name, description, mode: "SHADOW" }),
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
          <p>The bot starts in SHADOW mode with a draft configuration.</p>
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
            placeholder="XAU M1 Local Shadow"
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
          Mode
          <input value="SHADOW" disabled />
        </label>
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

