const AWARE_DATETIME_PATTERN = /^(\d{4})-(\d{2})-(\d{2})T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d+)?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$/;

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function isNonemptyString(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}

export function isNullableString(value: unknown): value is string | null | undefined {
  return value === null || value === undefined || typeof value === 'string';
}

export function isNonnegativeInteger(value: unknown): value is number {
  return isInteger(value) && value >= 0;
}

export function isInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value);
}

export function isFiniteDateTime(value: unknown): value is string {
  if (typeof value !== 'string') return false;
  const components = AWARE_DATETIME_PATTERN.exec(value);
  if (components === null || !Number.isFinite(Date.parse(value))) return false;
  // Date.parse rolls impossible days into the next month; reject that normalization.
  const year = Number(components[1]);
  const month = Number(components[2]);
  const day = Number(components[3]);
  if (year === 0 || month < 1 || month > 12 || day < 1) return false;
  // Day zero of the following month gives this month's last valid day.
  return day <= new Date(Date.UTC(year, month, 0)).getUTCDate();
}

export function isOneOf<Value extends string>(
  value: unknown,
  choices: readonly Value[],
): value is Value {
  return typeof value === 'string' && choices.includes(value as Value);
}

export function isArrayOf(
  data: unknown,
  predicate: (value: Record<string, unknown>) => boolean,
): boolean {
  return Array.isArray(data) && data.every((value) => isRecord(value) && predicate(value));
}

export function isUuid(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value)
  );
}

export function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

export function isOptionalNullable(
  value: unknown,
  predicate: (candidate: unknown) => boolean,
): boolean {
  return value === undefined || value === null || predicate(value);
}
