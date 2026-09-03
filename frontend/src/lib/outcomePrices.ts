import Decimal from 'decimal.js';

import runtimeContract from '$lib/runtimeContract.fixture.json';
import { isDecimal } from '$lib/valueGuards';

type UnitIntervalContract = {
  floor: string;
  ceiling: string;
  includeFloor: boolean;
};

export function isOutcomePrice(value: unknown): value is string {
  return isUnitIntervalDecimal(value, runtimeContract.outcomePrice);
}

export function isOutcomePayout(value: unknown): value is string {
  return isUnitIntervalDecimal(value, runtimeContract.outcomePayout);
}

function isUnitIntervalDecimal(
  value: unknown,
  contract: UnitIntervalContract
): value is string {
  if (!isDecimal(value)) return false;
  const decimal = new Decimal(value);
  const floor = new Decimal(contract.floor);
  const aboveFloor = contract.includeFloor
    ? decimal.gte(floor)
    : decimal.gt(floor);
  return aboveFloor && decimal.lte(contract.ceiling);
}
