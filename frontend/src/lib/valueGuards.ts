import Decimal from 'decimal.js';

const DECIMAL_PATTERN = /^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?$/;

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function isNonemptyString(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}

export function isNullableString(value: unknown): value is string | null | undefined {
  return value === null || value === undefined || typeof value === 'string';
}

export function isDecimal(value: unknown): value is string {
  if (typeof value !== 'string' || !DECIMAL_PATTERN.test(value)) return false;
  return new Decimal(value).isFinite();
}

export function isNonnegativeDecimal(value: unknown): value is string {
  return isDecimal(value) && new Decimal(value).gte(0);
}

export function isPositiveDecimal(value: unknown): value is string {
  return isDecimal(value) && new Decimal(value).gt(0);
}

export function isNonnegativeInteger(value: unknown): value is number {
  return isInteger(value) && value >= 0;
}

export function isInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value);
}

export function isFiniteDateTime(value: unknown): value is string {
  return typeof value === 'string' && Number.isFinite(Date.parse(value));
}

export function isOneOf<Value extends string>(
  value: unknown,
  choices: readonly Value[]
): value is Value {
  return typeof value === 'string' && choices.includes(value as Value);
}
