"""Splunk modular input that periodically exports NetBox objects."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Dict, Iterator, Optional

from splunklib.modularinput import Argument, Event, Scheme, Script

from netbox_client import NetBoxClient


ISO_FORMATS = ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z")


def _parse_bool(value: Optional[str], default: bool = True) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _parse_json(value: Optional[str]) -> Dict[str, str]:
    if not value:
        return {}
    value = value.strip()
    if not value:
        return {}
    try:
        data = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("Failed to parse JSON payload for query parameters") from exc
    if not isinstance(data, dict):
        raise ValueError("Query parameters must be provided as a JSON object")
    return {str(k): str(v) for k, v in data.items()}


def _guess_event_time(payload: Dict[str, object]) -> Optional[float]:
    for key in ("last_updated", "last_update", "created"):
        value = payload.get(key)
        if not isinstance(value, str):
            continue
        text = value.strip()
        for fmt in ISO_FORMATS:
            try:
                dt = datetime.strptime(text, fmt)
                return dt.timestamp()
            except ValueError:
                continue
    return None


class NetBoxInventoryInput(Script):
    """Modular input that streams NetBox resources into Splunk."""

    def get_scheme(self) -> Scheme:
        scheme = Scheme("NetBox Inventory")
        scheme.description = "Collect objects from NetBox over the REST API."
        scheme.use_external_validation = True
        scheme.use_single_instance = False

        scheme.add_argument(
            Argument(
                "netbox_url",
                title="NetBox URL",
                description="Base URL of the NetBox instance (for example https://netbox.example.com/api/).",
                required_on_create=True,
            )
        )
        scheme.add_argument(
            Argument(
                "token",
                title="Token",
                description="Personal API token with read permissions. Optional for publicly accessible data.",
                required_on_create=False,
            )
        )
        scheme.add_argument(
            Argument(
                "resource",
                title="Resource",
                description="NetBox resource path such as dcim/devices or ipam/ip-addresses.",
                required_on_create=True,
            )
        )
        scheme.add_argument(
            Argument(
                "query",
                title="Query parameters",
                description="Optional JSON object with additional filters passed to the API.",
                required_on_create=False,
            )
        )
        scheme.add_argument(
            Argument(
                "verify_ssl",
                title="Verify SSL",
                description="Whether to verify SSL certificates (true/false). Defaults to true.",
                required_on_create=False,
            )
        )
        scheme.add_argument(
            Argument(
                "timeout",
                title="Timeout",
                description="HTTP timeout in seconds. Defaults to 60.",
                required_on_create=False,
            )
        )
        return scheme

    def validate_input(self, definition):  # type: ignore[override]
        resource = definition.parameters.get("resource")
        if not resource:
            raise ValueError("A NetBox resource must be provided")
        if resource.startswith("/"):
            raise ValueError("The NetBox resource must not start with a leading slash")
        _parse_json(definition.parameters.get("query"))
        timeout = definition.parameters.get("timeout")
        if timeout:
            int(timeout)

    def stream_events(self, inputs, ew):  # type: ignore[override]
        for name, stanza in inputs.inputs.items():
            base_url = stanza.get("netbox_url")
            token = stanza.get("token") or None
            resource = stanza.get("resource")
            query = _parse_json(stanza.get("query"))
            verify_ssl = _parse_bool(stanza.get("verify_ssl"), default=True)
            timeout = stanza.get("timeout")
            timeout_seconds = int(timeout) if timeout else 60

            client = NetBoxClient(base_url, token=token, verify=verify_ssl, timeout=timeout_seconds)
            sourcetype = f"netbox:{resource.replace('/', '_')}"

            try:
                iterator: Iterator[dict] = client.iter_resource(resource, params=query)
            except Exception as exc:  # pragma: no cover - surfaced to Splunk logs
                raise RuntimeError(f"Failed to create NetBox iterator for stanza '{name}': {exc}") from exc

            for item in iterator:
                payload = json.dumps(item, ensure_ascii=False)
                event_time = _guess_event_time(item)
                event = Event(
                    data=payload,
                    stanza=name,
                    sourcetype=sourcetype,
                )
                if event_time is not None:
                    event.time = event_time
                if "name" in item and isinstance(item["name"], str):
                    event.host = item["name"]
                ew.write_event(event)


if __name__ == "__main__":
    NetBoxInventoryInput().run()
