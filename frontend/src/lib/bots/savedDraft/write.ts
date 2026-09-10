import { isClientRejection } from "$lib/api/http";
import { requestValidationIssues } from "$lib/api/requestErrors";
import { resourceLimitDetail } from "$lib/limits/validation";
import { DraftSaveFailure } from "./failure";

export async function resolveDraftWrite<T>(
  request: Promise<{ data?: T; error?: unknown; response?: Response }>,
): Promise<T> {
  // Only confirmed rejections permit retry: transport/server failures may have committed.
  let result;
  try {
    result = await request;
  } catch (error) {
    const knownRejection = resourceLimitDetail(error) !== undefined || requestValidationIssues(error).length > 0;
    throw new DraftSaveFailure(error, !knownRejection);
  }
  if (result.data !== undefined) return result.data;
  const rejected = resourceLimitDetail(result.error) !== undefined || isClientRejection(result.response?.status);
  throw new DraftSaveFailure(result.error, !rejected);
}
