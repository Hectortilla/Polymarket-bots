import { describe, expect, it } from 'vitest';

import {
  readableValidationMessage,
  requestErrorDetail,
  requestValidationIssues
} from './requestErrors';

describe('request error presentation', () => {
  it('keeps only valid FastAPI validation issues', () => {
    const validIssue = {
      loc: ['body', 'graph', 'nodes', 1, 'data', 'value'],
      msg: 'Value error, decimal graph constants must be finite decimal strings',
      type: 'value_error'
    };

    expect(
      requestValidationIssues({ detail: [validIssue, { msg: 'missing location' }] })
    ).toEqual([validIssue]);
  });

  it('reads small HTTP details without confusing them with validation arrays', () => {
    expect(
      requestErrorDetail({ detail: 'graph template name already exists' })
    ).toBe('graph template name already exists');
    expect(requestValidationIssues({ detail: 'not an array' })).toEqual([]);
  });

  it('removes transport wording and returns a complete sentence', () => {
    expect(
      readableValidationMessage('Value error, graph input cardinality is invalid')
    ).toBe('Graph input cardinality is invalid.');
  });
});
