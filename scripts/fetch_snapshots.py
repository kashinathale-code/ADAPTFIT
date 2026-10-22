"""
scripts/fetch_snapshots.py
==========================
Fetches empirical soil and OpenStreetMap (OSM) values for ADAPTFIT demonstration
locations from live external services when run on a working network, and saves them
into datasets/live_snapshots.json with source provenance, fetch date, and spatial resolution.

Rules:
- Never invent environmental values. If an external API returns null, an unknown class,
  or fails without prior data, record None/null.
- Uses descriptive User-Agent on all external calls (from Config.HTTP_USER_AGENT).
- Uses short connect timeouts (5 s) and 2 retries.
- Tries Overpass mirrors sequentially:
    1. overpass-api.de
    2. overpass.kumi.systems
    3. overpass.private.coffee
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
import sys
from typing import Any, Dict, List, Optional

# Add project root to sys.path so config and backend modules can be imported
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import requests
from config import Config
from backend.gis_processor import haversine_distance
from backend.data_fetcher import (
    RAWLS_1983_KS_TABLE,
    SOILGRIDS_PROPERTIES_URL,
    SOILGRIDS_SOURCE,
    SOILGRIDS_RESOLUTION,
    OSM_SOURCE,
    OSM_RESOLUTION,
    OSM_OPEN_SPACE_RADIUS_M,
    OSM_BUILDING_RADIUS_M,
    OVERPASS_MIRRORS,
    DEFAULT_CSV_PATH,
    DEFAULT_SNAPSHOTS_PATH,
    classify_usda_texture,
    infiltration_from_texture,
    load_sample_locations,
)

DEFAULT_OUTPUT_PATH = DEFAULT_SNAPSHOTS_PATH


def _get_headers() -> Dict[str, str]:
    """Return external HTTP headers with configured User-Agent."""
    ua = getattr(Config, "HTTP_USER_AGENT", "ADAPTFIT/1.0 (Climate Adaptation Transferability Tool)")
    return {"User-Agent": ua}


def fetch_soil_snapshot(
    lat: float,
    lon: float,
    timeout: float = 5.0,
    retries: int = 2,
) -> Optional[Dict[str, Any]]:
    """
    Fetch sand, clay, and silt percentages from SoilGrids v2.0 REST API at 5-15cm depth,
    divide raw means by d_factor (10), determine USDA texture class, and estimate
    Ks (mm/hr) using the Rawls et al. (1983) lookup table.
    """
    params = [
        ("lon", lon),
        ("lat", lat),
        ("property", "sand"),
        ("property", "clay"),
        ("property", "silt"),
        ("depth", "5-15cm"),
        ("value", "mean"),
    ]
    headers = _get_headers()
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    last_exc = None
    for attempt in range(retries + 1):
        try:
            resp = requests.get(
                SOILGRIDS_PROPERTIES_URL,
                params=params,
                headers=headers,
                timeout=(5.0, float(timeout)),
            )
            if resp.status_code >= 500 or resp.status_code == 429:
                resp.raise_for_status()
            resp.raise_for_status()
            data = resp.json()

            layers = data.get("properties", {}).get("layers", [])
            layer_map = {l["name"].lower(): l for l in layers if isinstance(l, dict) and l.get("name")}

            fractions: Dict[str, Optional[float]] = {}
            for prop in ("sand", "clay", "silt"):
                layer = layer_map.get(prop)
                if not layer:
                    fractions[prop] = None
                    continue
                dfactor = float(layer.get("unit_measure", {}).get("d_factor") or 10.0)
                depths = layer.get("depths", [])
                depth_entry = next((d for d in depths if d.get("label") == "5-15cm"), (depths[0] if depths else None))
                if depth_entry:
                    val = depth_entry.get("values", {}).get("mean")
                    if val is not None and isinstance(val, (int, float)):
                        fractions[prop] = float(val) / dfactor
                    else:
                        fractions[prop] = None
                else:
                    fractions[prop] = None

            if any(fractions.get(p) is None for p in ("sand", "clay", "silt")):
                return {
                    "value": None,
                    "unit": "mm/hr",
                    "source": SOILGRIDS_SOURCE,
                    "resolution": SOILGRIDS_RESOLUTION,
                    "fetch_date": today_str,
                    "transformation": "SoilGrids returned no sand/clay/silt values at 5-15cm depth (unmeasured or urban sealed surface)",
                }

            sand_pct = fractions["sand"]
            clay_pct = fractions["clay"]
            silt_pct = fractions["silt"]
            texture_class = classify_usda_texture(sand_pct, silt_pct, clay_pct)
            ks = infiltration_from_texture(texture_class) if texture_class else None
            trans = (
                f"SoilGrids 5-15cm (sand={sand_pct:.1f}%, silt={silt_pct:.1f}%, clay={clay_pct:.1f}%) -> "
                f"USDA texture '{texture_class.title()}' -> Ks = {ks} mm/hr via Rawls et al. (1983) Table 1"
                if ks is not None
                else f"SoilGrids 5-15cm fractions could not be mapped to Rawls et al. (1983) lookup table"
            )
            return {
                "value": ks,
                "unit": "mm/hr",
                "source": SOILGRIDS_SOURCE,
                "resolution": SOILGRIDS_RESOLUTION,
                "fetch_date": today_str,
                "transformation": trans,
            }
        except (requests.RequestException, Exception) as exc:
            last_exc = exc
            continue

    print(f"  [WARN] SoilGrids failed for ({lat}, {lon}) after {retries + 1} attempts: {last_exc}")
    return None


def fetch_osm_open_space_snapshot(
    lat: float,
    lon: float,
    timeout: float = 5.0,
    retries: int = 1,
) -> Optional[Dict[str, Any]]:
    """Query OSM Overpass mirrors in order for parks/greenery within 500 m."""
    query = (
        f"[out:json][timeout:{int(timeout)}];"
        f"("
        f'way["leisure"~"park|garden|nature_reserve|recreation_ground"](around:{OSM_OPEN_SPACE_RADIUS_M},{lat},{lon});'
        f'relation["leisure"~"park|garden|nature_reserve|recreation_ground"](around:{OSM_OPEN_SPACE_RADIUS_M},{lat},{lon});'
        f'way["landuse"~"grass|forest|meadow|village_green"](around:{OSM_OPEN_SPACE_RADIUS_M},{lat},{lon});'
        f");"
        f"out count;"
    )
    headers = _get_headers()
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for mirror in OVERPASS_MIRRORS:
        for _ in range(retries + 1):
            try:
                resp = requests.post(
                    mirror,
                    data={"data": query},
                    headers=headers,
                    timeout=(5.0, float(timeout)),
                )
                if resp.status_code >= 500 or resp.status_code == 429:
                    resp.raise_for_status()
                resp.raise_for_status()
                data = resp.json()
                total_count = data.get("elements", [])
                count_elems = [e for e in total_count if isinstance(e, dict) and e.get("type") == "count"]
                if count_elems:
                    total = int(count_elems[0].get("tags", {}).get("total", 0))
                else:
                    total = len(total_count)

                val = 1.0 if total > 0 else 0.0
                return {
                    "value": val,
                    "unit": "binary (1=present, 0=absent)",
                    "source": OSM_SOURCE,
                    "resolution": OSM_RESOLUTION,
                    "fetch_date": today_str,
                    "transformation": f"Overpass QL query: leisure/landuse parks within {OSM_OPEN_SPACE_RADIUS_M}m; result = {'present' if val else 'absent'} ({total} feature(s) found via {mirror})",
                }
            except Exception:
                continue

    print(f"  [WARN] OSM Overpass open_space failed for ({lat}, {lon}) across all mirrors")
    return None


def fetch_osm_building_distance_snapshot(
    lat: float,
    lon: float,
    timeout: float = 5.0,
    retries: int = 1,
) -> Optional[Dict[str, Any]]:
    """Query OSM Overpass mirrors in order for buildings within 200 m and compute nearest centroid."""
    query = (
        f"[out:json][timeout:{int(timeout)}];"
        f'way["building"](around:{OSM_BUILDING_RADIUS_M},{lat},{lon});'
        f"out bb;"
    )
    headers = _get_headers()
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for mirror in OVERPASS_MIRRORS:
        for _ in range(retries + 1):
            try:
                resp = requests.post(
                    mirror,
                    data={"data": query},
                    headers=headers,
                    timeout=(5.0, float(timeout)),
                )
                if resp.status_code >= 500 or resp.status_code == 429:
                    resp.raise_for_status()
                resp.raise_for_status()
                data = resp.json()
                elements = data.get("elements", [])
                buildings = [e for e in elements if isinstance(e, dict) and e.get("type") == "way"]

                if not buildings:
                    dist_m = float(OSM_BUILDING_RADIUS_M)
                    cnt = 0
                else:
                    min_dist_m = float("inf")
                    for bldg in buildings:
                        bounds = bldg.get("bounds")
                        if not bounds:
                            continue
                        c_lat = (bounds["minlat"] + bounds["maxlat"]) / 2.0
                        c_lon = (bounds["minlon"] + bounds["maxlon"]) / 2.0
                        d_km = haversine_distance(lat, lon, c_lat, c_lon)
                        d_m = d_km * 1000.0
                        if d_m < min_dist_m:
                            min_dist_m = d_m
                    dist_m = round(min_dist_m, 1) if min_dist_m < float("inf") else float(OSM_BUILDING_RADIUS_M)
                    cnt = len(buildings)

                return {
                    "value": dist_m,
                    "unit": "m",
                    "source": OSM_SOURCE,
                    "resolution": OSM_RESOLUTION,
                    "fetch_date": today_str,
                    "transformation": f"Nearest building centroid (bounding-box midpoint) from {cnt} OSM way[building] features within {OSM_BUILDING_RADIUS_M}m via {mirror}; distance = {dist_m}m",
                }
            except Exception:
                continue

    print(f"  [WARN] OSM Overpass building_distance failed for ({lat}, {lon}) across all mirrors")
    return None


def fetch_all_snapshots(
    csv_path: Optional[str] = None,
    output_path: Optional[str] = None,
    timeout: float = 5.0,
    retries: int = 1,
    force: bool = False,
) -> Dict[str, Any]:
    """
    Fetch soil and OSM values for demo locations from sample CSV and save to JSON.
    Preserves existing snapshot values if live network calls fail.
    """
    target_csv = csv_path or DEFAULT_CSV_PATH
    target_output = output_path or DEFAULT_OUTPUT_PATH

    # Load existing snapshots if present to avoid losing good data on network blips
    existing_data: Dict[str, Any] = {}
    if os.path.exists(target_output):
        try:
            with open(target_output, "r", encoding="utf-8") as fh:
                existing_data = json.load(fh)
        except Exception:
            existing_data = {}

    existing_locs = existing_data.get("locations", {})
    demo_locations = load_sample_locations(target_csv)
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    out_locations: Dict[str, Any] = dict(existing_locs)

    print(f"Fetching snapshots for {len(demo_locations)} demo locations...")
    for loc in demo_locations:
        name = loc["name"]
        lat = loc["latitude"]
        lon = loc["longitude"]
        key = name.lower().replace(" ", "_")
        print(f"\nProcessing {name} ({lat}, {lon})...")

        loc_record = out_locations.get(key, {"name": name, "latitude": lat, "longitude": lon, "factors": {}})
        factors = loc_record.setdefault("factors", {})

        # 1. Soil infiltration
        soil_snap = fetch_soil_snapshot(lat, lon, timeout=timeout, retries=retries)
        if soil_snap is not None:
            factors["soil_infiltration"] = soil_snap
            print(f"  soil_infiltration: {soil_snap['value']} {soil_snap['unit']}")
        elif "soil_infiltration" in factors and not force:
            print(f"  soil_infiltration: preserved existing ({factors['soil_infiltration']['value']})")

        # 2. OSM Open Space
        os_snap = fetch_osm_open_space_snapshot(lat, lon, timeout=timeout, retries=retries)
        if os_snap is not None:
            factors["open_space"] = os_snap
            print(f"  open_space: {os_snap['value']} {os_snap['unit']}")
        elif "open_space" in factors and not force:
            print(f"  open_space: preserved existing ({factors['open_space']['value']})")

        # 3. OSM Building Distance
        bd_snap = fetch_osm_building_distance_snapshot(lat, lon, timeout=timeout, retries=retries)
        if bd_snap is not None:
            factors["building_distance"] = bd_snap
            print(f"  building_distance: {bd_snap['value']} {bd_snap['unit']}")
        elif "building_distance" in factors and not force:
            print(f"  building_distance: preserved existing ({factors['building_distance']['value']})")

        out_locations[key] = loc_record

    snapshot_document = {
        "_description": "Empirical live data snapshots for ADAPTFIT demonstration locations. Used when live external APIs are slow or unreachable.",
        "fetch_date": today_str,
        "locations": out_locations,
    }

    os.makedirs(os.path.dirname(os.path.abspath(target_output)), exist_ok=True)
    with open(target_output, "w", encoding="utf-8") as fh:
        json.dump(snapshot_document, fh, indent=2)

    print(f"\nSaved snapshots successfully to: {target_output}")
    return snapshot_document


def main():
    parser = argparse.ArgumentParser(description="Fetch live snapshots for ADAPTFIT demo locations.")
    parser.add_argument("--csv", default=DEFAULT_CSV_PATH, help="Path to sample environmental data CSV")
    parser.add_argument("--output", default=DEFAULT_OUTPUT_PATH, help="Output JSON path for snapshots")
    parser.add_argument("--timeout", type=float, default=5.0, help="Connect/read timeout in seconds")
    parser.add_argument("--retries", type=int, default=2, help="Number of retries per request")
    parser.add_argument("--force", action="store_true", help="Overwrite existing values even if live call fails")
    args = parser.parse_args()

    fetch_all_snapshots(
        csv_path=args.csv,
        output_path=args.output,
        timeout=args.timeout,
        retries=args.retries,
        force=args.force,
    )


if __name__ == "__main__":
    main()
