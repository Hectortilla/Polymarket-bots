import { SERVICE_NAME } from "$lib/serviceIdentity";

/** Replace these approved placeholders before opening the public ingress. */
export const SERVICE_IDENTITY = {
  name: SERVICE_NAME,
  operator: "Deployment operator (placeholder)",
  supportEmail: null as string | null,
};
export const SUPPORT_PENDING = "Support contact is not configured. This preview is not open for public beta access.";
