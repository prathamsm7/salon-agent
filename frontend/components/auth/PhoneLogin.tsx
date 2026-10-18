"use client";

import { useState } from "react";
import { requestOtp, verifyOtp, type Account, type ApiError } from "@/lib/api";

type PhoneLoginProps = {
  onSignedIn: (token: string, user: Account) => void;
};

type Step = "phone" | "name" | "code";

export function PhoneLogin({ onSignedIn }: PhoneLoginProps) {
  const [step, setStep] = useState<Step>("phone");
  const [phone, setPhone] = useState("");
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  async function sendCode(nextName?: string) {
    setPending(true);
    setError("");
    try {
      await requestOtp(phone, nextName);
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
      const result = await verifyOtp(phone, code);
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
          if (step === "phone") void sendCode();
          else if (step === "name") void sendCode(name);
          else void submitCode();
        }}
      >
        <span className="kk-eyebrow">Kesh Kala</span>
        <h1>Sign in</h1>
        <p>
          {step === "code"
            ? "Enter the code from the API log. It stays valid for five minutes."
            : "Use your phone number. A new number asks for your name, then a one-time code."}
        </p>

        {error && (
          <p role="alert" className="kk-error-message">
            <span aria-hidden="true">!</span>
            {error}
          </p>
        )}

        {step === "phone" && (
          <label>
            Phone number
            <input
              inputMode="tel"
              autoComplete="tel"
              value={phone}
              onChange={(event) => setPhone(event.target.value)}
              placeholder="98765 43210"
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
            Code for {phone}
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

        {step !== "phone" && (
          <button
            type="button"
            className="kk-text-button"
            onClick={() => {
              setStep("phone");
              setCode("");
              setError("");
            }}
          >
            Use a different number
          </button>
        )}
      </form>
    </main>
  );
}
