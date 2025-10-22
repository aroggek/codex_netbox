# NetBox Connector for Splunk

This Splunk technology add-on provides two integration points with NetBox:

* **Modular input** – periodically pull any NetBox resource into Splunk. The
  resulting events can be accelerated into lookups/KV Store using standard
  saved searches or `| outputlookup`.
* **Streaming search command** – enrich alerts or ad-hoc searches with live
  NetBox context for one or many hosts.

Both entry points rely on the NetBox REST API and support pagination, filtering
and authenticated access via personal API tokens.

## Modular input: `netbox_inventory`

The modular input is implemented in `netbox_inventory.py`. Configure it from
**Settings → Data Inputs → NetBox Inventory** or by adding a stanza similar to
`inputs.conf`:

```conf
[netbox_inventory://devices]
netbox_url = https://netbox.example.com/api/
token = <token>
resource = dcim/devices
query = {"status": "active"}
interval = 3600
verify_ssl = true
```

Each stanza exports the specified NetBox resource. Returned objects are written
as JSON events whose sourcetype follows the pattern `netbox:<resource>`, for
example `netbox:dcim_devices`. The timestamp is derived from `last_updated`
when available. Use Splunk scheduled searches to push these events into a
lookup or KV Store collection if persistent tables are required.

## Search command: `netboxlookup`

The streaming command implemented in `netbox_lookup_command.py` enriches the
current search pipeline with data fetched from NetBox.

```spl
| netboxlookup netbox_url="https://netbox.example.com/api/" token="$NETBOX_TOKEN$" \
    resource="dcim/devices" match_field="dest" netbox_field="name" \
    fields="primary_ip4,address,status"
```

For each event the command looks up `resource` objects whose `netbox_field`
matches `match_field` in the Splunk event. Selected fields are appended with a
`netbox_` prefix (for example `netbox_status`). When the `fields` option is
omitted the full JSON payload is added to a single `netbox` field.

Additional static filters can be supplied through the `query` option using a
JSON object, enabling lookups within constrained device pools.

## Development notes

The legacy Elasticsearch integration supplied with the repository has been
removed. The add-on now focuses solely on NetBox connectivity and ships with a
minimal configuration footprint:

* `netbox_client.py` – lightweight helper handling pagination and errors.
* `netbox_inventory.py` – modular input entry point.
* `netbox_lookup_command.py` – streaming search command for enrichment.
* `commands.conf`, `props.conf`, `inputs.conf`, `app.conf` – add-on defaults.

All Python code targets Splunk's bundled Python 3 runtime.
