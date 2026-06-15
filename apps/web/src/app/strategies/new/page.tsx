"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { BotConfig, StrategyProfile } from "@/lib/types";
import { StrategyConfigForm } from "@/components/strategy-config-form";

export default function NewStrategyPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  return (
    <section>
      <header className="page-header">
        <div><span className="eyebrow">NEW GLOBAL STRATEGY</span><h1>Create strategy</h1><p>The strategy becomes active immediately.</p></div>
      </header>
      <div className="strategy-create-layout">
        <div className="panel form-grid">
          <label>Name<input required minLength={2} maxLength={120} value={name} onChange={(event) => setName(event.target.value)} /></label>
          <label>Description<textarea value={description} onChange={(event) => setDescription(event.target.value)} /></label>
        </div>
        <StrategyConfigForm
          submitLabel="Create strategy"
          onImportedFileName={setName}
          onSubmit={async (config: BotConfig) => {
            if (name.trim().length < 2) throw new Error("Strategy name is required");
            const profile = await api<StrategyProfile>("/api/v1/strategy-profiles", {
              method: "POST",
              body: JSON.stringify({ name, description, initial_config: config }),
            });
            router.push(`/strategies/${profile.id}`);
          }}
        />
      </div>
    </section>
  );
}
