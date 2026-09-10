import type { Side } from "$lib/api/generated";
import runtimeContract from "$lib/runtimeContract.fixture.json";

type SideContract = {
  [Key in keyof typeof runtimeContract.side]: Extract<Side, Key>;
};

const sideContract = runtimeContract.side as SideContract;
export const SIDE = {
  buy: sideContract.BUY,
  sell: sideContract.SELL,
} as const satisfies Record<string, Side>;

export function isSide(value: unknown): value is Side {
  return value === SIDE.buy || value === SIDE.sell;
}
