import Decimal from 'decimal.js';

const DECIMAL_PATTERN = /^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?$/;

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
