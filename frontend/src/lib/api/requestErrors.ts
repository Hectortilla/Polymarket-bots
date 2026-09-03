import type { ValidationError } from './generated';

export type RequestValidationIssue = Pick<
  ValidationError,
  'loc' | 'msg' | 'type'
>;

export function requestValidationIssues(
  error: unknown
): RequestValidationIssue[] {
  const detail = errorRecord(error)?.detail;
  if (!Array.isArray(detail)) return [];

  return detail.filter(isValidationIssue).map((issue) => ({
    loc: issue.loc,
    msg: issue.msg,
    type: issue.type
  }));
}

export function requestErrorDetail(error: unknown): string | undefined {
  const detail = errorRecord(error)?.detail;
  return typeof detail === 'string' && detail.trim() ? detail.trim() : undefined;
}

export function readableValidationMessage(message: string): string {
  const withoutPydanticPrefix = message.replace(/^Value error,\s*/i, '').trim();
  if (!withoutPydanticPrefix) return 'This value is invalid.';
  const sentence = withoutPydanticPrefix.replace(/^./, (letter) =>
    letter.toUpperCase()
  );
  return /[.!?]$/.test(sentence) ? sentence : `${sentence}.`;
}

function errorRecord(error: unknown): Record<string, unknown> | undefined {
  return error !== null && typeof error === 'object' && !Array.isArray(error)
    ? (error as Record<string, unknown>)
    : undefined;
}

function isValidationIssue(value: unknown): value is ValidationError {
  const issue = errorRecord(value);
  return Boolean(
    issue &&
      Array.isArray(issue.loc) &&
      issue.loc.every(
        (segment) => typeof segment === 'string' || typeof segment === 'number'
      ) &&
      typeof issue.msg === 'string' &&
      typeof issue.type === 'string'
  );
}
