import { hasOnlyResponseFields } from "$lib/api/responseValidation/fields";
import runtimeContract from "$lib/runtimeContract.fixture.json";

export function isHealthResponse(value: Record<string, unknown>): boolean {
  return hasOnlyResponseFields(value, "HealthResponse") && value.status === runtimeContract.healthStatus;
}
