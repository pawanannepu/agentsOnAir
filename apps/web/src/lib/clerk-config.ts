/**
 * Helpers to detect whether real Clerk credentials are configured.
 * Avoids throwing during `next build` imports, local dev, CI builds, or
 * unit tests that run without live Clerk API keys, while failing closed
 * at request time when NODE_ENV === "production".
 */

const PLACEHOLDER_KEYS = new Set([
  "pk_test_placeholder",
  "sk_test_placeholder",
]);

export class ClerkConfigurationError extends Error {
  readonly statusCode = 500;

  constructor(
    message = "Clerk authentication keys are missing or using placeholder values in production."
  ) {
    super(message);
    this.name = "ClerkConfigurationError";
  }
}

export function isProductionEnv(): boolean {
  return process.env.NODE_ENV === "production";
}

export function isClerkPublishableKeyConfigured(): boolean {
  const key = process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY?.trim();
  if (!key || PLACEHOLDER_KEYS.has(key)) {
    return false;
  }
  return (
    (key.startsWith("pk_test_") || key.startsWith("pk_live_")) &&
    key.length > 16
  );
}

export function isClerkServerConfigured(): boolean {
  if (!isClerkPublishableKeyConfigured()) {
    return false;
  }
  const secret = process.env.CLERK_SECRET_KEY?.trim();
  if (!secret || PLACEHOLDER_KEYS.has(secret)) {
    return false;
  }
  return (
    (secret.startsWith("sk_test_") || secret.startsWith("sk_live_")) &&
    secret.length > 16
  );
}

export function shouldBypassClerkInNonProd(): boolean {
  return !isProductionEnv() && !isClerkServerConfigured();
}

export function assertClerkConfiguredForRequest(): void {
  if (isProductionEnv() && !isClerkServerConfigured()) {
    throw new ClerkConfigurationError();
  }
}
