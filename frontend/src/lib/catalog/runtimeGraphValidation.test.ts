import { describe, expect, it } from 'vitest';

import type { NodeGraph } from '$lib/api/generated';
import parityContract from './graphValidationContract.fixture.json';
import { nodeGraphContractIsValid } from './runtimeGraphValidation';

describe('runtime graph validation parity', () => {
  for (const testCase of parityContract.cases) {
    it(testCase.name, () => {
      expect(nodeGraphContractIsValid(testCase.graph as NodeGraph)).toBe(
        testCase.valid
      );
    });
  }
});
