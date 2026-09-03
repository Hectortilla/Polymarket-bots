import { describe, expect, it } from 'vitest';
import type { RunStatus } from '$lib/api/generated';
import runtimeContract from '$lib/runtimeContract.fixture.json';

import { isRunStatus, RUN_STATUS_PRESENTATION } from './status';

describe('run status presentation', () => {
  it('gives every generated lifecycle state a readable label and action state', () => {
    for (const [status, presentation] of Object.entries(RUN_STATUS_PRESENTATION)) {
      expect(presentation.label).not.toContain('_');
      expect(presentation.label.length).toBeGreaterThan(0);
      expect(presentation.canStop && presentation.stopLabel === null).toBe(false);
      expect(presentation.terminal && presentation.stopLabel !== null).toBe(false);
      expect(status.length).toBeGreaterThan(0);
    }
  });

  it('derives lifecycle behavior from the generated status contract', () => {
    const terminal = new Set(runtimeContract.runStatus.terminal as RunStatus[]);
    const stoppable = new Set(runtimeContract.runStatus.stoppable as RunStatus[]);
    for (const [status, presentation] of Object.entries(
      RUN_STATUS_PRESENTATION
    ) as [RunStatus, (typeof RUN_STATUS_PRESENTATION)[RunStatus]][]) {
      expect(presentation.terminal).toBe(terminal.has(status));
      expect(presentation.canStop).toBe(stoppable.has(status));
    }
  });

  it('rejects inherited object keys as lifecycle states', () => {
    expect(isRunStatus('constructor')).toBe(false);
    expect(isRunStatus('__proto__')).toBe(false);
  });
});
