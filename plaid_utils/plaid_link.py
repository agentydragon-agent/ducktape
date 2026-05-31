"""Plaid Link-token and public-token helpers for the v0 web UI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from plaid_utils.link_profiles import LinkProfile, products_for_profile


@dataclass(frozen=True)
class PlaidLinkCreds:
    client_id: str
    secret: str
    env: str

    @property
    def base_url(self) -> str:
        if self.env == "sandbox":
            return "https://sandbox.plaid.com"
        if self.env == "production":
            return "https://production.plaid.com"
        raise ValueError(f"unsupported Plaid env: {self.env}")


@dataclass(frozen=True)
class LinkTokenResult:
    link_token: str
    products: list[str]


@dataclass(frozen=True)
class PublicTokenExchange:
    access_token: str
    item_id: str


class PlaidLinkClient:
    def __init__(
        self,
        creds: PlaidLinkCreds,
        *,
        client_name: str = "Plaid MCP",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._creds = creds
        self._client_name = client_name
        self._transport = transport

    async def create_link_token(
        self,
        *,
        profile: LinkProfile,
        redirect_uri: str,
        client_user_id: str,
        advanced_products: list[str] | None = None,
        access_token: str | None = None,
    ) -> LinkTokenResult:
        products = products_for_profile(profile, advanced_products)
        payload: dict[str, Any] = {
            "client_id": self._creds.client_id,
            "secret": self._creds.secret,
            "client_name": self._client_name,
            "user": {"client_user_id": client_user_id},
            "products": products,
            "country_codes": ["US"],
            "language": "en",
            "redirect_uri": redirect_uri,
            "transactions": {"days_requested": 730},
        }
        if access_token is not None:
            payload["access_token"] = access_token
        async with httpx.AsyncClient(transport=self._transport) as client:
            response = await client.post(f"{self._creds.base_url}/link/token/create", json=payload)
            if response.is_error:
                raise RuntimeError(f"Plaid /link/token/create {response.status_code}: {response.text}")
            return LinkTokenResult(link_token=response.json()["link_token"], products=products)

    async def create_update_link_token(
        self, *, access_token: str, redirect_uri: str, client_user_id: str, additional_products: list[str] | None = None
    ) -> LinkTokenResult:
        payload: dict[str, Any] = {
            "client_id": self._creds.client_id,
            "secret": self._creds.secret,
            "client_name": self._client_name,
            "user": {"client_user_id": client_user_id},
            "country_codes": ["US"],
            "language": "en",
            "redirect_uri": redirect_uri,
            "access_token": access_token,
        }
        if additional_products:
            payload["additional_consented_products"] = additional_products
        async with httpx.AsyncClient(transport=self._transport) as client:
            response = await client.post(f"{self._creds.base_url}/link/token/create", json=payload)
            if response.is_error:
                raise RuntimeError(f"Plaid /link/token/create {response.status_code}: {response.text}")
            return LinkTokenResult(link_token=response.json()["link_token"], products=additional_products or [])

    async def exchange_public_token(self, public_token: str) -> PublicTokenExchange:
        async with httpx.AsyncClient(transport=self._transport) as client:
            response = await client.post(
                f"{self._creds.base_url}/item/public_token/exchange",
                json={"client_id": self._creds.client_id, "secret": self._creds.secret, "public_token": public_token},
            )
            response.raise_for_status()
            data = response.json()
            return PublicTokenExchange(access_token=data["access_token"], item_id=data["item_id"])

    async def remove_item(self, access_token: str) -> None:
        async with httpx.AsyncClient(transport=self._transport) as client:
            response = await client.post(
                f"{self._creds.base_url}/item/remove",
                json={"client_id": self._creds.client_id, "secret": self._creds.secret, "access_token": access_token},
            )
            response.raise_for_status()
