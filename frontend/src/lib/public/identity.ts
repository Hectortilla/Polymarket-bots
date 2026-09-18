import { SERVICE_NAME } from "$lib/serviceIdentity";

/** Public contact details. Operational ownership is recorded in the release checklist. */
export const SERVICE_IDENTITY = {
  name: SERVICE_NAME,
  supportEmail: "operator@polybotlab.com" as string | null,
};
export const SUPPORT_PENDING = "Email support is not available yet.";
