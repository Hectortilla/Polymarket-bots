"""Validate controller credentials and render container secret files."""

from pydantic import BaseModel, ConfigDict, Field

from scripts.deployment.storage import SecretFile, database_url, redis_url


class ContainerSecret(BaseModel):
    model_config = ConfigDict(frozen=True, hide_input_in_errors=True)
    name: SecretFile
    content: str = Field(min_length=1, repr=False)


class ContainerSecretInputs(BaseModel):
    model_config = ConfigDict(frozen=True, hide_input_in_errors=True)
    database_password: str = Field(
        pattern=r"^[a-f0-9]{64}$", min_length=64, max_length=64, repr=False
    )
    smtp_username: str = Field(min_length=1, repr=False)
    smtp_password: str = Field(min_length=1, repr=False)

    def render(self) -> list[ContainerSecret]:
        values = {
            SecretFile.POSTGRES_PASSWORD: self.database_password,
            SecretFile.DATABASE_URL: database_url(self.database_password),
            SecretFile.REDIS_URL: redis_url(),
            SecretFile.SMTP_USERNAME: self.smtp_username,
            SecretFile.SMTP_PASSWORD: self.smtp_password,
        }
        return [
            ContainerSecret(name=name, content=value) for name, value in values.items()
        ]
