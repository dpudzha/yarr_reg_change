"""
Grafana query helper for fetching register monitoring values.

Queries InfluxDB (via Grafana) for M1-M4 REG[V] values from the
"RegisterRead" bucket.
"""

import os
import requests
from datetime import datetime, timedelta

GRAFANA_URL = "http://193.206.86.196:3000"
DATASOURCE_UID = "ffbqtv11qyv40c"
SLOTS = ["M1", "M2", "M3", "M4"]


def _load_env():
    """Load variables from .env file next to this script (if it exists)."""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.isfile(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())


_load_env()

GRAFANA_API_KEY = os.environ.get("GRAFANA_API_KEY")


def _headers():
    """Build request headers."""
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    if GRAFANA_API_KEY:
        h["Authorization"] = f"Bearer {GRAFANA_API_KEY}"
    return h


def fetch_register_values():
    """
    Query M1-M4 REG[V] values from InfluxDB via Grafana.

    Returns:
        dict mapping slot to value, e.g. {"M1": 1.23, "M2": 4.56, ...}
        or None on error.
    """
    now = datetime.utcnow()
    time_from = now - timedelta(minutes=5)

    query = (
        'from(bucket: "RegisterRead")'
        ' |> range(start: -5m)'
        ' |> filter(fn: (r) => r["_measurement"] == "M1"'
        ' or r["_measurement"] == "M2"'
        ' or r["_measurement"] == "M3"'
        ' or r["_measurement"] == "M4")'
        ' |> filter(fn: (r) => r["_field"] == "REG[V]")'
        ' |> last()'
    )

    payload = {
        "queries": [
            {
                "refId": "A",
                "datasource": {"type": "influxdb", "uid": DATASOURCE_UID},
                "query": query,
            }
        ],
        "from": str(int(time_from.timestamp() * 1000)),
        "to": str(int(now.timestamp() * 1000)),
    }

    try:
        url = f"{GRAFANA_URL}/api/ds/query"
        resp = requests.post(url, json=payload, headers=_headers(), timeout=10)
        resp.raise_for_status()
        data = resp.json()

        result = {s: None for s in SLOTS}
        frames = data.get("results", {}).get("A", {}).get("frames", [])
        for frame in frames:
            # Measurement name is in schema.name (e.g. "M1", "M2")
            measurement = frame.get("schema", {}).get("name", "")
            if measurement in result:
                values = frame.get("data", {}).get("values", [])
                if len(values) >= 2 and values[1]:
                    result[measurement] = round(float(values[1][-1]), 2)

        return result
    except requests.RequestException as e:
        print(f"  [Grafana] Query failed: {e}")
        return None
    except (KeyError, IndexError, TypeError, ValueError) as e:
        print(f"  [Grafana] Error parsing response: {e}")
        return None


def load_module_map(filepath):
    """
    Load a module mapping file. Each line: <slot> <module_serial>
    e.g.:
        M1 20UPGM23211190
        M2 20UPGR93210231

    Returns:
        dict mapping module serial to slot label, e.g.
        {"20UPGM23211190": "M1", "20UPGR93210231": "M2", ...}
    """
    module_to_slot = {}
    with open(filepath, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) >= 2:
                slot, module_serial = parts[0], parts[1]
                module_to_slot[module_serial] = slot
    return module_to_slot
