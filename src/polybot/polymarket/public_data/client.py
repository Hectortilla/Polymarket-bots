"""Shared SDK-client lifecycle for public adapter assemblies."""

from __future__ import annotations

from dataclasses import dataclass

from polymarket import AsyncPublicClient

from polybot.polymarket.client_lifecycle import close_owned_public_client


@dataclass(slots=True)
class _PublicClientOwner:
    """Own one optional official public client for an adapter assembly."""

    _owned_client: AsyncPublicClient | None

    async def close(self) -> None:
        """Close the SDK client only when this bundle created it."""
        client = self._owned_client
        if client is not None:
            await close_owned_public_client(client)
            self._owned_client = None


def _acquire_public_client(
    client: AsyncPublicClient | None,
) -> tuple[AsyncPublicClient, bool]:
    if client is None:
        return AsyncPublicClient(), True
    return client, False
