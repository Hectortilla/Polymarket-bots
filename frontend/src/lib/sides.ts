import type { Side } from '$lib/api/generated';
import { SIDE } from '$lib/charts/contracts';

export function isSide(value: unknown): value is Side {
  return value === SIDE.buy || value === SIDE.sell;
}
