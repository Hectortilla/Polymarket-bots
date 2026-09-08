import Decimal from 'decimal.js';
import catalogContract from './catalogContract.fixture.json';

export function graphNumberIsValid(value: unknown): value is string {
  if (typeof value !== 'string' || value.length > catalogContract.maximumNumberTextLength || !new RegExp(catalogContract.numberPattern).test(value)) return false;
  try {
    const number = new Decimal(value);
    return number.isFinite() && Math.abs(number.e) <= catalogContract.maximumNumberExponent;
  } catch { return false; }
}
