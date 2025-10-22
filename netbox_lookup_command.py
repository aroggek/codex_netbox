"""Streaming search command that enriches events with NetBox data."""
from __future__ import annotations

import json
from typing import Dict, Iterable, Optional

from splunklib.searchcommands import Configuration, Option, StreamingCommand, dispatch

from netbox_client import NetBoxClient


def _parse_fields(value: Optional[str]) -> Optional[Iterable[str]]:
    if not value:
        return None
    parts = [part.strip() for part in value.split(',') if part.strip()]
    return parts or None


@Configuration()
class NetBoxLookupCommand(StreamingCommand):
    """Enrich Splunk events with attributes fetched from NetBox."""

    netbox_url = Option(require=True, doc="Base URL of the NetBox instance.")
    token = Option(require=False, doc="Personal API token with read access to the requested resource.")
    resource = Option(require=True, doc="NetBox resource path (e.g. dcim/devices).")
    match_field = Option(require=False, default="name", doc="Field in the Splunk event to look up.")
    netbox_field = Option(require=False, default="name", doc="Field in NetBox used to match values.")
    fields = Option(require=False, doc="Comma separated list of NetBox fields to copy into the event.")
    verify_ssl = Option(require=False, default="true", doc="Whether to verify SSL certificates.")
    timeout = Option(require=False, default="60", doc="HTTP timeout in seconds.")
    query = Option(require=False, doc="Additional static filters encoded as JSON.")

    def _get_client(self) -> NetBoxClient:
        verify_ssl = str(self.verify_ssl).strip().lower() in {"1", "true", "yes", "on"}
        timeout_seconds = int(self.timeout)
        return NetBoxClient(self.netbox_url, token=self.token or None, verify=verify_ssl, timeout=timeout_seconds)

    def _base_filters(self) -> Dict[str, str]:
        if not self.query:
            return {}
        try:
            payload = json.loads(self.query)
        except json.JSONDecodeError as exc:
            raise ValueError("Query filters must be a JSON object") from exc
        if not isinstance(payload, dict):
            raise ValueError("Query filters must be a JSON object")
        return {str(k): str(v) for k, v in payload.items()}

    def stream(self, records):  # type: ignore[override]
        client = self._get_client()
        base_filters = self._base_filters()
        field_list = list(_parse_fields(self.fields) or [])
        cache: Dict[str, Optional[dict]] = {}

        for record in records:
            value = record.get(self.match_field)
            if not value:
                yield record
                continue

            cache_key = str(value)
            if cache_key not in cache:
                params = dict(base_filters)
                params[self.netbox_field] = cache_key
                cache[cache_key] = client.get_first(self.resource, params=params)

            payload = cache[cache_key]
            if not payload:
                yield record
                continue

            if field_list:
                for field in field_list:
                    record[f"netbox_{field}"] = payload.get(field)
            else:
                record.setdefault("netbox", json.dumps(payload, ensure_ascii=False))
            yield record


def dispatch_netbox_lookup_command():
    dispatch(NetBoxLookupCommand, module_name=__name__)


if __name__ == "__main__":
    dispatch_netbox_lookup_command()
