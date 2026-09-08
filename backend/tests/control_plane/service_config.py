"""Shared opt-in service settings for control-plane integration tests."""


TEST_POSTGRES_URL_ENV = "POLYBOT_TEST_POSTGRES_URL"
TEST_REDIS_URL_ENV = "POLYBOT_TEST_REDIS_URL"
POSTGRES_NOT_CONFIGURED_SKIP_REASON = (
    f"{TEST_POSTGRES_URL_ENV} is not configured"
)
POSTGRES_AND_REDIS_NOT_CONFIGURED_SKIP_REASON = (
    f"{TEST_POSTGRES_URL_ENV} and {TEST_REDIS_URL_ENV} are not configured"
)
