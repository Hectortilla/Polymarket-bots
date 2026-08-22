import { describe, expect, it } from 'vitest';

import { RUN_STATUS_PRESENTATION } from './status';

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
});
