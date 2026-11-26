export type OrgForbiddenCode = "org_inactive" | "org_missing";

export interface OrgForbiddenDetail {
  code: OrgForbiddenCode;
  message: string;
}

export const ORG_FORBIDDEN_EVENT = "aoa:org-forbidden";

export function isOrgForbiddenCode(value: unknown): value is OrgForbiddenCode {
  return value === "org_inactive" || value === "org_missing";
}

export function extractOrgForbiddenDetail(
  payload: unknown
): OrgForbiddenDetail | null {
  if (!payload || typeof payload !== "object") {
    return null;
  }
  const record = payload as Record<string, unknown>;
  const detail =
    record.detail && typeof record.detail === "object"
      ? (record.detail as Record<string, unknown>)
      : record;

  if (isOrgForbiddenCode(detail.code)) {
    return {
      code: detail.code,
      message:
        typeof detail.message === "string" && detail.message
          ? detail.message
          : "Active organization access is required.",
    };
  }
  return null;
}

export function dispatchOrgForbiddenEvent(detail: OrgForbiddenDetail): void {
  if (typeof window === "undefined") {
    return;
  }
  window.dispatchEvent(
    new CustomEvent<OrgForbiddenDetail>(ORG_FORBIDDEN_EVENT, { detail })
  );
}
