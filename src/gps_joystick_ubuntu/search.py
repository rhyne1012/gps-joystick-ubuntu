"""Free geocoding place search via Photon with Nominatim fallback."""

from __future__ import annotations

import httpx

PHOTON_URL = "https://photon.komoot.io/api/"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "gps-joystick-ubuntu/0.1 (https://github.com/rhyne1012/gps-joystick-ubuntu)"


def _format_photon_address(props: dict[str, object]) -> str:
    parts: list[str] = []
    for key in ("country", "city", "district", "street", "housenumber"):
        value = props.get(key)
        if isinstance(value, str) and value and value not in parts:
            parts.append(value)
    return " ".join(parts)


async def _query_photon(
    client: httpx.AsyncClient,
    query: str,
    lat: float | None,
    lon: float | None,
    limit: int,
) -> list[dict[str, object]]:
    params: dict[str, str | int | float] = {"q": query, "limit": limit}
    if lat is not None and lon is not None:
        params["lat"] = lat
        params["lon"] = lon
    resp = await client.get(PHOTON_URL, params=params)
    resp.raise_for_status()
    payload = resp.json()
    results: list[dict[str, object]] = []
    for feature in payload.get("features", []):
        coords = (feature.get("geometry") or {}).get("coordinates") or []
        if len(coords) < 2:
            continue
        props = feature.get("properties") or {}
        name = str(props.get("name") or props.get("street") or query).strip()
        address = _format_photon_address(props) or str(props.get("state") or "")
        results.append(
            {
                "name": name,
                "address": address,
                "latitude": float(coords[1]),
                "longitude": float(coords[0]),
                "source": "photon",
            }
        )
    return results


async def _query_nominatim(
    client: httpx.AsyncClient, query: str, limit: int
) -> list[dict[str, object]]:
    resp = await client.get(
        NOMINATIM_URL,
        params={"q": query, "format": "jsonv2", "limit": limit, "addressdetails": 1},
    )
    resp.raise_for_status()
    items = resp.json()
    results: list[dict[str, object]] = []
    for item in items:
        try:
            lat = float(item["lat"])
            lon = float(item["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        display = str(item.get("display_name") or query)
        name = str(item.get("name") or display.split(",")[0]).strip()
        results.append(
            {
                "name": name,
                "address": display,
                "latitude": lat,
                "longitude": lon,
                "source": "nominatim",
            }
        )
    return results


async def search_places(
    query: str,
    lat: float | None = None,
    lon: float | None = None,
    limit: int = 6,
) -> dict[str, object]:
    """Search for places or addresses using Photon, falling back to Nominatim."""
    cleaned = query.strip()
    if not cleaned:
        return {"results": [], "error": None}
    bounded_limit = min(10, max(1, limit))

    async with httpx.AsyncClient(
        timeout=6.0,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8"},
    ) as client:
        try:
            results = await _query_photon(client, cleaned, lat, lon, bounded_limit)
            if results:
                return {"results": results, "error": None}
        except Exception:
            pass

        try:
            results = await _query_nominatim(client, cleaned, bounded_limit)
            return {"results": results, "error": None}
        except Exception as err:
            return {
                "results": [],
                "error": f"地點搜尋失敗，請確認網路連線（{type(err).__name__}）。",
            }
