"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("admin@goldie.local");
  const [password, setPassword] = useState("change-me-now");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await api<{ access_token: string }>(
        "/api/v1/auth/login",
        { method: "POST", body: JSON.stringify({ email, password }) },
        false,
      );
      localStorage.setItem("goldie_token", result.access_token);
      router.push("/bots");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Login failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-screen">
      <form className="login-card" onSubmit={submit}>
        <span className="eyebrow">LOCAL CONTROL PLANE</span>
        <h1>Goldie</h1>
        <p>Read-only XAU/USD research environment.</p>
        <label>
          Email
          <input value={email} onChange={(event) => setEmail(event.target.value)} />
        </label>
        <label>
          Password
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </label>
        {error && <div className="error-box">{error}</div>}
        <button className="button button-primary" disabled={busy}>
          {busy ? "Signing in..." : "Sign in"}
        </button>
        <span className="readonly-badge">READ ONLY / NO ORDER EXECUTION</span>
      </form>
    </div>
  );
}

