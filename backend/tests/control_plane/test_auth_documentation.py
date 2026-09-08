"""Keep the approved account policy inventory aligned with its runtime owner."""

from pathlib import Path

from api.auth import policy


def test_documented_auth_policy_matches_runtime():
    root = Path(__file__).resolve().parents[3]
    architecture = (root / "docs/web-control-plane-architecture.md").read_text()
    documented = architecture.split("<!-- auth-policy:start -->\n", 1)[1].split(
        "<!-- auth-policy:end -->", 1
    )[0]
    assert documented == auth_policy_table()
    readme = (root / "README.md").read_text()
    assert (
        f"{policy.PASSWORD_MIN_LENGTH}–{policy.PASSWORD_MAX_LENGTH} characters"
        in readme
    )
    assert (
        f"Sessions expire after {policy.SESSION_LIFETIME_SECONDS // 86400} days"
        in readme
    )


def auth_policy_table() -> str:
    rows = (
        (
            "Password length (Unicode characters)",
            f"{policy.PASSWORD_MIN_LENGTH}–{policy.PASSWORD_MAX_LENGTH}",
        ),
        ("Email maximum length", policy.EMAIL_MAX_LENGTH),
        ("Argon2id memory (KiB)", policy.ARGON_MEMORY_KIB),
        ("Argon2id iterations", policy.ARGON_ITERATIONS),
        ("Argon2id parallelism", policy.ARGON_PARALLELISM),
        ("Session entropy (bytes)", policy.SESSION_TOKEN_BYTES),
        ("Absolute session lifetime (seconds)", policy.SESSION_LIFETIME_SECONDS),
        ("Maximum session recheck interval (seconds)", policy.SESSION_RECHECK_SECONDS),
        ("Authentication request maximum (bytes)", policy.AUTH_BODY_MAX_BYTES),
        ("Rate-limit window (seconds)", policy.AUTH_RATE_WINDOW_SECONDS),
        ("Login attempts per window", policy.LOGIN_ATTEMPT_LIMIT),
        ("Registration attempts per window", policy.REGISTER_ATTEMPT_LIMIT),
    )
    return (
        "\n| Policy | Value |\n| --- | --- |\n"
        + "".join(f"| {label} | {value} |\n" for label, value in rows)
        + "\n"
    )
