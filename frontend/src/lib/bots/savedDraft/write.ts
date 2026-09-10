import { isClientRejection } from '$lib/api/http';
import { requestValidationIssues } from '$lib/api/requestErrors';
import { resourceLimitDetail } from '$lib/limits/validation';
import { DraftSaveFailure, type DraftWrite } from './failure';

export async function resolveDraftWrite<T>(stage: DraftWrite, request: Promise<{ data?: T; error?: unknown; response?: Response }>): Promise<T> {
  // Only confirmed rejections permit retry: transport/server failures may have committed.
  let result;
  try { result = await request; }
  catch (error) {
    const knownRejection = resourceLimitDetail(error) !== undefined || requestValidationIssues(error).length > 0;
    throw new DraftSaveFailure(stage, error, !knownRejection);
  }
  if (result.data !== undefined) return result.data;
  const rejected = resourceLimitDetail(result.error) !== undefined || isClientRejection(result.response?.status);
  throw new DraftSaveFailure(stage, result.error, !rejected);
}
