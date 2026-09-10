import contract from "$lib/runtimeContract.fixture.json";
export const RESOURCE_LIMIT_DETAIL = "The requested resource is full. Try again shortly.";
export const RESOURCE_LIMIT_CASES = [undefined, ...Object.values(contract.resourceLimitCodes)];
