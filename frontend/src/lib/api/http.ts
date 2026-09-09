import runtimeContract from '../runtimeContract.fixture.json' with { type: 'json' };

export const HTTP_STATUS = runtimeContract.httpStatus;
export const JSON_CONTENT_TYPE = runtimeContract.auth.jsonContentType;
export const CONTENT_TYPE_HEADER = runtimeContract.auth.contentTypeHeader;

export const IDEMPOTENCY_KEY_HEADER = runtimeContract.idempotencyKeyHeader;
