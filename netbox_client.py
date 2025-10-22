"""Lightweight NetBox API client used by the Splunk connector."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Dict, Iterator, Optional, Union
from urllib.parse import urljoin

import requests


class NetBoxAPIError(RuntimeError):
    """Raised when the NetBox API returns an unexpected response."""

    def __init__(self, message: str, status: Optional[int] = None, payload: Optional[dict] = None) -> None:
        super().__init__(message)
        self.status = status
        self.payload = payload or {}


@dataclass
class NetBoxClient:
    """Small helper around :mod:`requests` to talk to NetBox."""

    base_url: str
    token: Optional[str] = None
    verify: Union[bool, str] = True
    timeout: int = 60

    def __post_init__(self) -> None:
        if not self.base_url:
            raise ValueError("NetBox base URL must be provided")
        if not self.base_url.endswith('/'):
            self.base_url = f"{self.base_url}/"
        self._session = requests.Session()
        self._session.headers.update({"Accept": "application/json"})
        if self.token:
            self._session.headers.update({"Authorization": f"Token {self.token}"})

    def _request(self, method: str, path: str, params: Optional[Dict[str, Union[str, int]]] = None) -> requests.Response:
        url = urljoin(self.base_url, path.lstrip('/'))
        response = self._session.request(method, url, params=params, timeout=self.timeout, verify=self.verify)
        if not response.ok:
            try:
                payload = response.json()
            except ValueError:
                payload = None
            raise NetBoxAPIError(
                f"NetBox API request failed with status {response.status_code}",
                status=response.status_code,
                payload=payload,
            )
        return response

    def iter_resource(
        self,
        resource: str,
        params: Optional[Dict[str, Union[str, int]]] = None,
    ) -> Iterator[dict]:
        """Iterate over all objects of the given resource handling pagination automatically."""

        next_url: Optional[str] = None
        current_params = dict(params or {})
        while True:
            response = self._request("GET", next_url or resource, params=current_params if not next_url else None)
            try:
                data = response.json()
            except ValueError as exc:
                raise NetBoxAPIError("NetBox API returned non JSON response", payload={"raw": response.text}) from exc

            if isinstance(data, dict) and {"results", "next"}.issubset(data.keys()):
                for item in data.get("results", []):
                    yield item
                next_url = data.get("next")
                if not next_url:
                    break
                current_params = None
            elif isinstance(data, list):
                for item in data:
                    yield item
                break
            elif isinstance(data, dict):
                # Single object response
                yield data
                break
            else:
                raise NetBoxAPIError(
                    "Unexpected response structure from NetBox",
                    payload={"raw": json.dumps(data)},
                )

    def get_first(
        self,
        resource: str,
        params: Optional[Dict[str, Union[str, int]]] = None,
    ) -> Optional[dict]:
        """Return the first item for the resource matching the parameters."""

        for item in self.iter_resource(resource, params=params):
            return item
        return None

    def get_by_id(self, resource: str, object_id: Union[str, int]) -> Optional[dict]:
        """Fetch a single object by its numeric identifier."""

        try:
            response = self._request("GET", f"{resource.rstrip('/')}/{object_id}/")
        except NetBoxAPIError as exc:
            if exc.status == 404:
                return None
            raise
        try:
            return response.json()
        except ValueError as exc:
            raise NetBoxAPIError("NetBox API returned non JSON response", payload={"raw": response.text}) from exc
