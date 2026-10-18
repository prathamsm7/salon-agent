"use client";

import { useState } from "react";
import { requestOtp, verifyOtp, type Account, type ApiError } from "@/lib/api";

type EmailLoginProps = {
  onSignedIn: (token: string, user: Account) => void;
};

type Step = "email" | "name" | "code";

export function EmailLogin({ onSignedIn }: EmailLoginProps) {
  const [step, setStep] = useState<Step>("email");
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  async function sendCode(nextName?: string) {
    setPending(true);
    setError("");
    try {
      await requestOtp(email, nextName);
      setStep("code");
    } catch (caught) {
      const apiError = caught as ApiError;
      if (apiError.code === "name_required") {
        setStep("name");
        setError("");
      } else {
        setError(apiError.message || "Could not send the code.");
      }
    } finally {
      setPending(false);
    }
  }

  async function submitCode() {
    setPending(true);
    setError("");
    try {
      const result = await verifyOtp(email, code);
      onSignedIn(result.token, result.user);
    } catch (caught) {
      const apiError = caught as ApiError;
      setError(apiError.message || "That code did not work.");
    } finally {
      setPending(false);
    }
  }

  return (
    <main className="kk-sign-in">
      <form
        className="kk-sign-card"
        onSubmit={(event) => {
          event.preventDefault();
          if (step === "email") void sendCode();
          else if (step === "name") void sendCode(name);
          else void submitCode();
        }}
      >
        <span className="kk-eyebrow">Kesh Kala</span>
        <h1>Sign in</h1>
        <p>
          {step === "code"
            ? "Enter the code from your email. It stays valid for five minutes."
            : "Use your email. A new address asks for your name, then a one-time code."}
        </p>

        {error && (
          <p role="alert" className="kk-error-message">
            <span aria-hidden="true">!</span>
            {error}
          </p>
        )}

        {step === "email" && (
          <label>
            Email
            <input
              type="email"
              autoComplete="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="priya@email.com"
              required
            />
          </label>
        )}

        {step === "name" && (
          <label>
            Your name
            <input
              autoComplete="name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Priya Shah"
              required
            />
          </label>
        )}

        {step === "code" && (
          <label>
            Code for {email}
            <input
              inputMode="numeric"
              autoComplete="one-time-code"
              value={code}
              onChange={(event) => setCode(event.target.value)}
              placeholder="000000"
              required
            />
          </label>
        )}

        <button className="kk-primary" disabled={pending}>
          {pending ? "Please wait…" : step === "code" ? "Sign in" : "Continue"}
        </button>

        {step !== "email" && (
          <button
            type="button"
            className="kk-text-button"
            onClick={() => {
              setStep("email");
              setCode("");
              setError("");
            }}
          >
            Use a different email
          </button>
        )}
      </form>
    </main>
  );
}
