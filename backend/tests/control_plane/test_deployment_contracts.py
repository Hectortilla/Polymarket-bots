"""Rendered controller/host contracts and static Compose/workflow parity."""

import json
import re
from pathlib import Path

import pytest
import yaml
from api.auth.config import AUTH_ALLOW_HTTP_ENV, AUTH_ORIGIN_ENV
from api.auth.mail.config import (
    DEFAULT_SMTP_SECURITY,
    SMTP_FROM_ENV,
    SMTP_HOST_ENV,
    SMTP_PASSWORD_ENV,
    SMTP_PORT_ENV,
    SMTP_SECURITY_ENV,
    SMTP_USERNAME_ENV,
)
from api.database import DATABASE_URL_ENV
from api.deployment.release import RELEASE_ID_ENV
from api.deployment.services import (
    ENTRYPOINT_SERVICE,
    POSTGRES_SERVICE,
    REDIS_SERVICE,
    DeploymentService,
)
from api.deployment.settings import (
    API_PORT,
    ENVIRONMENT_ENV,
    PROXY_ADDRESS_ENV,
    STORAGE_PROBE_PATH_ENV,
)
from api.deployment.settings import Environment as RuntimeEnvironment
from api.execution.config import REDIS_URL_ENV
from api.http.routes.paths import API_PREFIX, HEALTH_PATH
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from polybot.framework.config.constants import BOT_LIVE_ENABLED_ENV, BOT_MODE_ENV
from polybot.framework.config.mode import BotMode

from scripts.deployment.ansible_contract import (
    DeploymentContract,
    HostOperationNames,
    HostPaths,
    RuntimeKeys,
    SecretFileNames,
    ServiceUnitNames,
    TransportFileNames,
    deployment_contract,
)
from scripts.deployment.bundle.contracts import RELEASE_BUNDLE_FILENAME
from scripts.deployment.controller import ControllerOperation
from scripts.deployment.dotenv import parse_values
from scripts.deployment.github import RELEASE_WORKFLOW_ARTIFACT_NAME
from scripts.deployment.identity import DeploymentOperation
from scripts.deployment.images import ImageField
from scripts.deployment.inventory import SUPPORTED_ARCHITECTURES, DeploymentInventory
from scripts.deployment.network import (
    API_ADDRESS,
    EDGE_GATEWAY,
    EDGE_SUBNET,
    ENTRYPOINT_ADDRESS,
    ENTRYPOINT_HEALTH_PATH,
    ENTRYPOINT_HEALTH_PATH_ENV,
    ENTRYPOINT_HEALTH_PORT,
    ENTRYPOINT_HTTP_PORT,
    HEALTH_HTTP_STATUS,
)
from scripts.deployment.paths import (
    CI_INPUTS_FILENAME,
    DEFAULT_APP_DIRECTORY,
    SECRETS_DIRECTORY_NAME,
    SOURCE_COMPOSE_PATH,
)
from scripts.deployment.provisioning import ContainerSecretInputs
from scripts.deployment.publication import PublicationOutput
from scripts.deployment.release_inputs import ReleaseIdentity, ReleaseInputs
from scripts.deployment.runtime_contracts import (
    DEFAULT_HTTP_PORT,
    DEFAULT_SMTP_PORT,
    HTTP_PORT_ENV,
    SECRETS_DIRECTORY_ENV,
)
from scripts.deployment.storage import (
    POSTGRES_DATABASE,
    POSTGRES_USER,
    SecretFile,
    database_url,
    redis_url,
)
from scripts.deployment.tailscale import (
    PRIVATE_HTTPS_PORT,
    TAILNET_CI_TAG,
    TAILNET_HOST_TAG,
)
from scripts.deployment.toolchain import (
    ANSIBLE_CORE_VERSION,
    PYTHON_VERSION,
    TAILSCALE_ACTION_VERSION,
    UV_VERSION,
)
from scripts.deployment.units import (
    BACKUP_CHECK_TIMER_UNIT,
    BACKUP_TIMER_UNIT,
    MONITOR_TIMER_UNIT,
)
from scripts.host_operations.config import HostOperationsConfig
from scripts.host_operations.contracts import REQUIRED_COMPLETED_UNITS, HostOperation
from scripts.host_operations.policy import BACKUP_CHECK_CALENDAR, MONITOR_CALENDAR


def inventory_values():
    values = yaml.safe_load(
        Path("deploy/ansible/inventory/production.example.yml").read_text()
    )["all"]["children"]["polybot"]["vars"]
    return values | {
        "polybot_origin": "https://fixture.example.ts.net",
        "polybot_backups_enabled": True,
        "polybot_sftp_host": "storage.example.com",
        "polybot_sftp_port": 22,
        "polybot_sftp_user": "fixture",
        "polybot_sftp_directory": "/backups/polybot",
        "polybot_smtp_username": "fixture",
        "polybot_smtp_password": "fixture-password",
    }


def render_template(name, values=None):
    env = Environment(
        loader=FileSystemLoader("deploy/ansible/templates"), undefined=StrictUndefined
    )
    env.filters["to_json"] = json.dumps
    return env.get_template(name).render(
        **(
            inventory_values()
            | {
                "deployment_contract": deployment_contract(),
                "release_tag": "v1.2.3",
                "operation": DeploymentOperation.DEPLOY,
            }
            | (values or {})
        )
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("polybot_root", "/"),
        ("polybot_arch", "x86"),
        ("polybot_origin", "https://example.com"),
        ("polybot_http_port", 80),
        ("polybot_smtp_host", "bad\nheader"),
        ("polybot_smtp_port", 0),
        ("polybot_smtp_security", "local"),
        ("polybot_smtp_from", "bad-address"),
        ("polybot_alert_to", "bad\naddress@example.com"),
        ("polybot_sftp_host", "-invalid"),
        ("polybot_sftp_port", 65536),
        ("polybot_sftp_user", "injected\nuser"),
        ("polybot_sftp_directory", "/backups"),
    ],
)
def test_controller_inventory_rejects_unsafe_inputs(field, value):
    with pytest.raises(ValueError):
        DeploymentInventory.model_validate(inventory_values() | {field: value})


@pytest.mark.parametrize(
    "count,distribution,machine",
    [(2, "Debian", "x86_64"), (1, "Ubuntu", "x86_64"), (1, "Debian", "aarch64")],
)
def test_controller_rejects_wrong_target_before_mutation(count, distribution, machine):
    with pytest.raises(ValueError):
        DeploymentInventory.model_validate(inventory_values()).require_host(
            count, distribution, machine
        )


def test_ci_inventory_adapter_returns_only_supported_platform():
    for arch in SUPPORTED_ARCHITECTURES:
        inventory = DeploymentInventory.from_ansible_inventory(
            {
                "_meta": {
                    "hostvars": {"one": inventory_values() | {"polybot_arch": arch}}
                }
            }
        )
        assert inventory.arch == arch
    with pytest.raises(ValueError):
        DeploymentInventory.from_ansible_inventory({"_meta": {"hostvars": {}}})


def test_runtime_template_uses_the_manifest_key_contract():
    rendered = parse_values(render_template("runtime.env.j2"))
    expected = {
        AUTH_ORIGIN_ENV,
        HTTP_PORT_ENV,
        SECRETS_DIRECTORY_ENV,
        SMTP_HOST_ENV,
        SMTP_PORT_ENV,
        SMTP_SECURITY_ENV,
        SMTP_FROM_ENV,
    }
    assert set(rendered) == expected
    assert rendered[HTTP_PORT_ENV] == str(DEFAULT_HTTP_PORT)
    assert rendered[SMTP_PORT_ENV] == str(DEFAULT_SMTP_PORT)
    assert rendered[SMTP_SECURITY_ENV] == DEFAULT_SMTP_SECURITY
    assert rendered[SECRETS_DIRECTORY_ENV] == str(
        DEFAULT_APP_DIRECTORY / SECRETS_DIRECTORY_NAME
    )


@pytest.mark.parametrize("security,starttls", [("starttls", "on"), ("tls", "off")])
def test_msmtp_template_renders_authenticated_secure_transport(security, starttls):
    rendered = render_template("msmtprc.j2", {"polybot_smtp_security": security})
    assert "auth on" in rendered and "tls on" in rendered
    assert f"tls_starttls {starttls}" in rendered
    assert f"/secrets/{SecretFile.SMTP_PASSWORD}" in rendered
    assert inventory_values()["polybot_smtp_password"] not in rendered


@pytest.mark.parametrize("value", ["", "a" * 63, "a" * 65, "g" * 64, "a" * 64 + "\n"])
def test_retained_database_password_rejected_before_any_secret_render(value):
    with pytest.raises(ValueError):
        ContainerSecretInputs.model_validate(
            {"database_password": value, "smtp_username": "u", "smtp_password": "p"}
        )


def test_rendered_storage_urls_and_secrets_share_runtime_owner():
    password = "a" * 64
    secrets = {
        item.name: item.content
        for item in ContainerSecretInputs.model_validate(
            {"database_password": password, "smtp_username": "u", "smtp_password": "p"}
        ).render()
    }
    assert set(secrets) == set(SecretFile)
    assert secrets[SecretFile.DATABASE_URL] == database_url(password)
    assert secrets[SecretFile.REDIS_URL] == redis_url()
    compose = yaml.safe_load(SOURCE_COMPOSE_PATH.read_text())
    assert set(compose["secrets"]) == set(SecretFile)
    for name, secret in compose["secrets"].items():
        assert secret["file"].endswith("/" + name)
        assert SECRETS_DIRECTORY_ENV in secret["file"]


def test_compose_caddy_network_ports_and_health_contract():
    compose = yaml.safe_load(SOURCE_COMPOSE_PATH.read_text())
    services = compose["services"]
    proxy = services[ENTRYPOINT_SERVICE]
    api = services[DeploymentService.API]
    assert proxy["ports"] == [
        f"127.0.0.1:${{{HTTP_PORT_ENV}:-{DEFAULT_HTTP_PORT}}}:{ENTRYPOINT_HTTP_PORT}"
    ]
    assert proxy["environment"][ENTRYPOINT_HEALTH_PATH_ENV] == ENTRYPOINT_HEALTH_PATH
    assert (
        f":{ENTRYPOINT_HEALTH_PORT}$${{{ENTRYPOINT_HEALTH_PATH_ENV}}}"
        in proxy["healthcheck"]["test"][-1]
    )
    assert f":{API_PORT}{API_PREFIX}{HEALTH_PATH}" in api["healthcheck"]["test"][-1]
    assert api["environment"][PROXY_ADDRESS_ENV] == ENTRYPOINT_ADDRESS
    assert proxy["networks"]["edge"]["ipv4_address"] == ENTRYPOINT_ADDRESS
    assert api["networks"]["edge"]["ipv4_address"] == API_ADDRESS
    assert compose["networks"]["edge"]["ipam"]["config"] == [
        {"subnet": EDGE_SUBNET, "gateway": EDGE_GATEWAY}
    ]
    caddy = Path("deploy/Caddyfile").read_text()
    for expected in [
        f"{EDGE_GATEWAY}/32",
        f"http://127.0.0.1:{ENTRYPOINT_HEALTH_PORT}",
        f"http://:{ENTRYPOINT_HTTP_PORT}",
        "{$" + ENTRYPOINT_HEALTH_PATH_ENV + "} " + str(HEALTH_HTTP_STATUS),
        f"api:{API_PORT}",
    ]:
        assert expected in caddy


def test_units_share_operations_timeout_and_do_not_hide_lost_runtime():
    contract = deployment_contract()
    for service in REQUIRED_COMPLETED_UNITS:
        unit = render_template(service + ".j2")
        operation = HostOperation(
            service.removeprefix("polybot-").removesuffix(".service")
        )
        assert f" {operation}\n" in unit
        assert f"TimeoutStartSec={contract['timeout']}" in unit
        assert "ConditionPathExistsGlob=" in unit
        assert "ConditionPathExists=" not in unit
    assert f"OnCalendar={contract['calendar']}" in render_template(
        BACKUP_TIMER_UNIT + ".j2"
    )
    for operation in DeploymentOperation:
        unit = render_template("activate.service.j2", {"operation": operation})
        assert ("--rollback" in unit) == (operation is DeploymentOperation.ROLLBACK)


def test_workflow_toolchain_and_operation_contracts():
    workflow = yaml.safe_load(Path(".github/workflows/release.yml").read_text())
    steps = workflow["jobs"]["bundle"]["steps"] + workflow["jobs"]["deploy"]["steps"]
    for step in steps:
        if step.get("uses", "").startswith("astral-sh/setup-uv"):
            assert step["with"]["version"] == UV_VERSION
        if step.get("uses", "").startswith("tailscale/github-action"):
            assert step["with"]["version"] == TAILSCALE_ACTION_VERSION
            assert step["with"]["tags"] == TAILNET_CI_TAG
        if "uv tool install ansible-core" in step.get("run", ""):
            assert "ansible-core==" + ANSIBLE_CORE_VERSION in step["run"]
    events = workflow.get("on", workflow.get(True))
    assert events["workflow_dispatch"]["inputs"]["operation"]["options"] == list(
        DeploymentOperation
    )
    for event in ["push", "workflow_dispatch"]:
        for reuse in ["true", "false"]:
            scope = {
                "github": {"event_name": event},
                "steps": {"existing": {"outputs": {"reuse": reuse}}},
            }
            manual = next(
                step
                for step in steps
                if step.get("name")
                == "Manual operations require an existing published release"
            )["if"]
            # Evaluate the actual restricted workflow expression with Jinja's
            # equivalent operators; a string-presence assertion misses inverted gates.
            evaluation = Environment().compile_expression(manual.replace("&&", "and"))(
                **scope
            )
            assert evaluation == (event == "workflow_dispatch" and reuse != "true")
            for step in steps:
                if step.get("uses", "").startswith("docker/build-push-action"):
                    assert Environment().compile_expression(step["if"])(**scope) == (
                        reuse != "true"
                    )


def test_static_workflows_and_examples_match_deployment_owners():
    for path in Path(".github/workflows").glob("*.yml"):
        workflow = yaml.safe_load(path.read_text())
        for job in workflow["jobs"].values():
            for step in job.get("steps", []):
                action = step.get("uses", "")
                if action.startswith("astral-sh/setup-uv"):
                    assert step["with"]["version"] == UV_VERSION
                if (
                    action.startswith("actions/upload-artifact")
                    and step.get("with", {}).get("name")
                    == RELEASE_WORKFLOW_ARTIFACT_NAME
                ):
                    assert Path(step["with"]["path"]).name == RELEASE_BUNDLE_FILENAME
                if action.startswith("tailscale/github-action"):
                    assert step["with"]["version"] == TAILSCALE_ACTION_VERSION
                if "uv tool install ansible-core" in step.get("run", ""):
                    assert f"ansible-core=={ANSIBLE_CORE_VERSION}" in step["run"]
    release = yaml.safe_load(Path(".github/workflows/release.yml").read_text())
    upload = next(
        step
        for step in release["jobs"]["bundle"]["steps"]
        if step.get("uses", "").startswith("actions/upload-artifact")
    )
    download = next(
        step
        for step in release["jobs"]["deploy"]["steps"]
        if step.get("uses", "").startswith("actions/download-artifact")
    )
    assert (
        upload["with"]["name"]
        == download["with"]["name"]
        == RELEASE_WORKFLOW_ARTIFACT_NAME
    )
    for step in release["jobs"]["bundle"]["steps"]:
        if "steps.existing.outputs." in step.get("if", ""):
            assert f"steps.existing.outputs.{PublicationOutput.REUSE}" in step["if"]
    assert (
        f"ghcr.io/astral-sh/uv:{UV_VERSION}"
        in Path("deploy/backend.Dockerfile").read_text()
    )
    assert inventory_values()["polybot_http_port"] == DEFAULT_HTTP_PORT
    for operation in DeploymentOperation:
        play = yaml.safe_load(Path(f"deploy/ansible/{operation}.yml").read_text())[0]
        assert play["vars"]["operation"] == operation


def test_generated_host_config_and_ci_private_inputs_match_consumers(tmp_path):
    contract = deployment_contract()
    assert set(contract) == set(DeploymentContract.__annotations__)
    for name, schema in [
        ("runtime_keys", RuntimeKeys),
        ("paths", HostPaths),
        ("secret_files", SecretFileNames),
        ("transport_files", TransportFileNames),
        ("operations", HostOperationNames),
        ("service_units", ServiceUnitNames),
    ]:
        assert set(contract[name]) == set(schema.__annotations__)
    bootstrap = yaml.safe_load(Path("deploy/ansible/bootstrap.yml").read_text())[0]
    task = next(
        task
        for task in bootstrap["tasks"]
        if task.get("name") == "Install host operational configuration"
    )
    env = Environment(undefined=StrictUndefined)
    env.filters["to_nice_json"] = json.dumps
    payload = env.from_string(task["ansible.builtin.copy"]["content"]).render(
        **inventory_values(), deployment_contract=contract
    )
    config = HostOperationsConfig.model_validate_json(payload)
    assert config.http_port == DEFAULT_HTTP_PORT
    assert config.remote.startswith(contract["backup_remote"] + ":")
    values = {
        "RELEASE_TAG": "v1.2.3",
        "RELEASE_COMMIT": "a" * 40,
        "REGISTRY_USERNAME": "fixture",
        "REGISTRY_TOKEN": "private-fixture",
        "OPERATION": DeploymentOperation.ROLLBACK,
    }
    inputs = ReleaseInputs.from_environment(values, tmp_path / RELEASE_BUNDLE_FILENAME)
    destination = tmp_path / "inputs.json"
    inputs.write(destination)
    decoded = json.loads(destination.read_text())
    assert (
        ReleaseIdentity.model_validate(decoded).operation
        is DeploymentOperation.ROLLBACK
    )
    assert decoded["registry_token"] == values["REGISTRY_TOKEN"]
    assert values["REGISTRY_TOKEN"] not in repr(inputs)
    assert destination.stat().st_mode & 0o777 == 0o600


def test_compose_safety_storage_and_full_environment_contract():
    compose = yaml.safe_load(SOURCE_COMPOSE_PATH.read_text())
    services = compose["services"]
    common = compose["x-application"]["environment"]
    expected_common = {
        ENVIRONMENT_ENV,
        RELEASE_ID_ENV,
        AUTH_ORIGIN_ENV,
        AUTH_ALLOW_HTTP_ENV,
        DATABASE_URL_ENV + "_FILE",
        REDIS_URL_ENV + "_FILE",
        PROXY_ADDRESS_ENV,
        BOT_MODE_ENV,
        BOT_LIVE_ENABLED_ENV,
    }
    assert set(common) == expected_common
    assert common[ENVIRONMENT_ENV] == RuntimeEnvironment.PRODUCTION
    assert common[BOT_MODE_ENV] == BotMode.PAPER
    assert common[BOT_LIVE_ENABLED_ENV] == common[AUTH_ALLOW_HTTP_ENV] == "false"
    smtp_keys = {
        SMTP_HOST_ENV,
        SMTP_PORT_ENV,
        SMTP_SECURITY_ENV,
        SMTP_FROM_ENV,
        SMTP_USERNAME_ENV + "_FILE",
        SMTP_PASSWORD_ENV + "_FILE",
    }
    assert (
        set(services[DeploymentService.API]["environment"])
        == expected_common | smtp_keys
    )
    assert set(
        services[DeploymentService.RECOVERY]["environment"]
    ) == expected_common | {STORAGE_PROBE_PATH_ENV}
    image_roles = {
        DeploymentService.API: ImageField.BACKEND,
        DeploymentService.WORKER: ImageField.BACKEND,
        DeploymentService.RECOVERY: ImageField.BACKEND,
        DeploymentService.MIGRATE: ImageField.BACKEND,
        ENTRYPOINT_SERVICE: ImageField.FRONTEND,
        POSTGRES_SERVICE: ImageField.POSTGRES,
        REDIS_SERVICE: ImageField.REDIS,
    }
    for service, field in image_roles.items():
        assert services[service]["image"].startswith("${" + field + ":?")
    postgres = services[POSTGRES_SERVICE]
    assert postgres["environment"]["POSTGRES_USER"] == POSTGRES_USER
    assert postgres["environment"]["POSTGRES_DB"] == POSTGRES_DATABASE
    assert (
        postgres["healthcheck"]["test"][-1]
        == f"pg_isready -U {POSTGRES_USER} -d {POSTGRES_DATABASE}"
    )
    for field, secret in [
        (DATABASE_URL_ENV, SecretFile.DATABASE_URL),
        (REDIS_URL_ENV, SecretFile.REDIS_URL),
        (SMTP_USERNAME_ENV, SecretFile.SMTP_USERNAME),
        (SMTP_PASSWORD_ENV, SecretFile.SMTP_PASSWORD),
    ]:
        assert (
            services[DeploymentService.API]["environment"][field + "_FILE"]
            == f"/run/secrets/{secret}"
        )


def test_deployment_callers_and_policy_disclosures_share_owners():
    for path in [
        *Path("deploy/ansible").rglob("*.yml"),
        *Path(".github/workflows").glob("*.yml"),
    ]:
        for operation in re.findall(
            r"scripts\.deployment\.controller[ ,]+([a-z-]+)", path.read_text()
        ):
            ControllerOperation(operation)
    policy = Path("deploy/tailscale-policy.example.hujson").read_text()
    docs = Path("docs/beta-deployment.md").read_text()
    for tag in [TAILNET_HOST_TAG, TAILNET_CI_TAG]:
        assert tag in policy and tag in docs
    assert f"{TAILNET_HOST_TAG}:{PRIVATE_HTTPS_PORT}" in policy
    for path in Path(".github/workflows").glob("*.yml"):
        for job in yaml.safe_load(path.read_text())["jobs"].values():
            for step in job.get("steps", []):
                if step.get("uses", "").startswith("tailscale/github-action"):
                    assert step["with"]["tags"] == TAILNET_CI_TAG
    assert f"ansible-core=={ANSIBLE_CORE_VERSION}" in docs
    assert UV_VERSION in docs
    operations_docs = Path("docs/beta-operations.md").read_text()
    for calendar in (BACKUP_CHECK_CALENDAR, MONITOR_CALENDAR):
        assert f"`{calendar}`" in operations_docs
    contract = deployment_contract()
    for unit, calendar in [
        (BACKUP_CHECK_TIMER_UNIT, BACKUP_CHECK_CALENDAR),
        (MONITOR_TIMER_UNIT, MONITOR_CALENDAR),
    ]:
        assert f"OnCalendar={calendar}" in render_template(unit + ".j2")
    assert (
        contract["activation_poll_interval"] * contract["activation_poll_retries"]
        > contract["activation_timeout"]
    )
    tasks = yaml.safe_load(Path("deploy/ansible/tasks/activate.yml").read_text())
    polls = [task for task in tasks if "retries" in task]
    assert len(polls) == 2
    for task in polls:
        assert "deployment_contract.activation_poll_retries" in task["retries"]
        assert "deployment_contract.activation_poll_interval" in task["delay"]


def test_static_examples_and_release_transport_names_match_owners():
    example = parse_values(Path("deploy/release.env.example").read_text())
    for key in [
        *ImageField,
        RELEASE_ID_ENV,
        AUTH_ORIGIN_ENV,
        HTTP_PORT_ENV,
        SECRETS_DIRECTORY_ENV,
        SMTP_HOST_ENV,
        SMTP_PORT_ENV,
        SMTP_SECURITY_ENV,
        SMTP_FROM_ENV,
    ]:
        assert key in example
    assert example[HTTP_PORT_ENV] == str(DEFAULT_HTTP_PORT)
    assert example[SMTP_PORT_ENV] == str(DEFAULT_SMTP_PORT)
    assert example[SMTP_SECURITY_ENV] == DEFAULT_SMTP_SECURITY
    assert set(parse_values(Path("deploy/infrastructure.env").read_text())) == {
        ImageField.POSTGRES,
        ImageField.REDIS,
    }
    release = Path(".github/workflows/release.yml").read_text()
    assert release.count(CI_INPUTS_FILENAME) == 2
    paths = re.findall(r'bundle/[^\s"\']+\.tar\.gz', release)
    assert paths and all(Path(path).name == RELEASE_BUNDLE_FILENAME for path in paths)
    assert (
        f"python:{PYTHON_VERSION}-slim" in Path("deploy/backend.Dockerfile").read_text()
    )
