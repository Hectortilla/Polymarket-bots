import runtimeContract from "$lib/runtimeContract.fixture.json";

export function isHealthResponse(value: Record<string, unknown>): boolean {
  return value.status === runtimeContract.healthStatus;
}
