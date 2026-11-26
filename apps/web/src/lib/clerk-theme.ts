export const CLERK_TASK_URLS = {
  "choose-organization": "/onboarding/organization",
} as const;

/**
 * Serializable Clerk appearance configuration aligned with the zinc OKLCH dark
 * design tokens in globals.css.
 */
export const clerkAppearance = {
  variables: {
    colorPrimary: "oklch(72% 0.19 155)",
    colorTextOnPrimaryBackground: "oklch(14.5% 0.005 285)",
    colorBackground: "oklch(17% 0.006 285)",
    colorInputBackground: "oklch(14.5% 0.005 285)",
    colorInputText: "oklch(98% 0.002 285)",
    colorText: "oklch(98% 0.002 285)",
    colorTextSecondary: "oklch(65% 0.01 285)",
    colorDanger: "oklch(55% 0.22 25)",
    colorSuccess: "oklch(72% 0.19 155)",
    colorWarning: "oklch(78% 0.16 75)",
    colorNeutral: "oklch(65% 0.01 285)",
    borderRadius: "0.5rem",
    fontFamily: "var(--font-geist-sans), system-ui, sans-serif",
    fontFamilyButtons: "var(--font-geist-sans), system-ui, sans-serif",
  },
  elements: {
    rootBox: "w-full",
    cardBox: "w-full shadow-xl border border-border bg-card rounded-xl",
    card: "bg-card border border-border shadow-none rounded-xl",
    headerTitle: "text-foreground font-semibold tracking-tight",
    headerSubtitle: "text-muted-foreground text-xs",
    socialButtonsBlockButton:
      "bg-secondary hover:bg-accent text-foreground border border-border transition-colors",
    socialButtonsBlockButtonText: "text-foreground font-medium text-xs",
    dividerLine: "bg-border",
    dividerText: "text-muted-foreground text-xs",
    formFieldLabel: "text-foreground text-xs font-medium",
    formFieldInput:
      "bg-background border-border text-foreground placeholder:text-muted-foreground focus:ring-2 focus:ring-ring rounded-md text-sm",
    formButtonPrimary:
      "bg-emerald-500 hover:bg-emerald-400 text-zinc-950 font-semibold shadow-sm transition-colors",
    footerActionText: "text-muted-foreground text-xs",
    footerActionLink:
      "text-emerald-400 hover:text-emerald-300 font-medium text-xs",
    identityPreviewText: "text-foreground text-xs",
    identityPreviewEditButton: "text-emerald-400 hover:text-emerald-300",
    organizationSwitcherTrigger:
      "w-full justify-between rounded-lg border border-border bg-zinc-900/60 px-2.5 py-2 text-xs text-foreground hover:bg-accent/60 transition-colors focus-visible:ring-2 focus-visible:ring-ring",
    organizationSwitcherTriggerIcon: "text-muted-foreground",
    organizationPreviewMainIdentifier: "text-foreground text-xs font-medium",
    organizationPreviewSecondaryIdentifier:
      "text-muted-foreground text-[11px] font-mono",
    organizationSwitcherPopoverCard:
      "bg-popover border border-border shadow-xl rounded-xl text-popover-foreground",
    organizationSwitcherPopoverActionButton:
      "text-foreground hover:bg-accent rounded-md text-xs",
    organizationListPreviewItem:
      "border-b border-border/60 last:border-b-0 hover:bg-accent/40 transition-colors",
    userButtonPopoverCard:
      "bg-popover border border-border shadow-xl rounded-xl text-popover-foreground",
    userButtonPopoverActionButton:
      "text-foreground hover:bg-accent rounded-md text-xs",
    alert: "border border-destructive/40 bg-destructive/10 text-foreground",
    alertText: "text-xs text-foreground",
  },
} as const;
