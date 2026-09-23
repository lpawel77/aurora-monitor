#!/usr/bin/env python3
"""Aurora monitor using NOAA SWPC services.

Przykład użycia:
    python aurora.py --lat 52.23 --lon 21.01
    python aurora.py --lat 50 --lon 20 --limit 5
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from typing import Any, Iterable, List, Sequence, Tuple
from urllib import error, request

OVATION_URL = "https://services.swpc.noaa.gov/json/ovation_aurora_latest.json"
ALERTS_URL = "https://services.swpc.noaa.gov/products/alerts.json"


def fetch_json(url: str) -> Any:
    """Pobiera JSON z adresu URL."""
    try:
        with request.urlopen(url, timeout=20) as response:
            payload = response.read()
            return json.loads(payload.decode("utf-8"))
    except error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} przy pobieraniu {url}") from exc
    except Exception as exc:  # pragma: no cover - zależne od sieci
        raise RuntimeError(f"Nie udało się pobrać danych z {url}: {exc}") from exc


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def isoformat_utc(value: Any) -> str:
    if not value:
        return "brak"
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(float(value), tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        if isinstance(value, str):
            text = value.strip()
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            if text.endswith("UTC"):
                return text
            dt = datetime.fromisoformat(text)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        pass
    return str(value)


def as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def normalize_longitude(value: float) -> float:
    while value < -180:
        value += 360
    while value > 180:
        value -= 360
    return value


def recursive_search(obj: Any, keys: Sequence[str]) -> Any:
    """Wyszukuje klucze w zagnieżdżonej strukturze JSON."""
    if isinstance(obj, dict):
        for key in keys:
            if key in obj:
                return obj[key]
        for value in obj.values():
            result = recursive_search(value, keys)
            if result is not None:
                return result
    elif isinstance(obj, list):
        for item in obj:
            result = recursive_search(item, keys)
            if result is not None:
                return result
    return None


def extract_ovation_grid(payload: Any) -> Tuple[List[float], List[float], List[List[float]]]:
    """Wyciąga siatkę OVATION z możliwych struktur odpowiedzi NOAA.

    Dla typowego payloadu API są klucze "lat", "lon" oraz "data" lub "ovation".
    """
    latitudes = []
    longitudes = []
    grid = []

    latitudes = as_list(recursive_search(payload, ("lat", "latitude", "latitude_grid")))
    longitudes = as_list(recursive_search(payload, ("lon", "longitude", "longitude_grid")))

    grid = recursive_search(payload, ("data", "ovation", "aurora", "grid", "aurora_ovation"))
    if isinstance(grid, list):
        if grid and isinstance(grid[0], list):
            return latitudes, longitudes, grid
        if grid and isinstance(grid[0], dict):
            # Jeśli to jest lista rekordów z współrzędnymi, nie da się tego odczytać sensownie,
            # więc dołączamy jedynie tabelę z pola "value" / "probability".
            values = []
            for item in grid:
                if isinstance(item, dict):
                    row = item.get("value")
                    if isinstance(row, list):
                        values.append(row)
            if values:
                return latitudes, longitudes, values

    # Fallback: jeśli odpowiedź ma format "{\"coordinates\": [ ... ]}" albo inny zagnieżdżony.
    if not grid:
        coords = recursive_search(payload, ("coordinates", "coords"))
        if isinstance(coords, list):
            for item in coords:
                if isinstance(item, dict):
                    if "lat" in item and "lon" in item and "value" in item:
                        latitudes.append(float(item["lat"]))
                        longitudes.append(float(item["lon"]))
                        grid.append([float(item["value"])])

    if not latitudes or not longitudes or not grid:
        raise ValueError("Nie udało się rozpoznać siatki aurory z API NOAA SWPC.")

    return latitudes, longitudes, grid


def nearest_index(values: Sequence[float], target: float) -> int:
    if not values:
        return 0
    return min(range(len(values)), key=lambda idx: abs(float(values[idx]) - float(target)))


def _lon_distance(a: float, b: float) -> float:
    """Odległość kątowa dwóch długości geograficznych z uwzględnieniem zawijania 0/360."""
    diff = abs(a - b) % 360
    return min(diff, 360 - diff)


def extract_flat_points(payload: Any) -> List[Tuple[float, float, float]]:
    """Wyciąga płaską listę (lon 0-360, lat, wartość) z aktualnego formatu NOAA SWPC,
    gdzie payload["coordinates"] to lista [lon, lat, wartość]."""
    coords = payload.get("coordinates") if isinstance(payload, dict) else None
    if isinstance(coords, list) and coords and isinstance(coords[0], list) and len(coords[0]) == 3:
        return [(float(c[0]), float(c[1]), float(c[2])) for c in coords]
    return []


def probability_label(probability: float) -> str:
    if probability >= 70:
        return "Bardzo wysoki"
    if probability >= 50:
        return "Wysoki"
    if probability >= 30:
        return "Średni"
    if probability >= 10:
        return "Niski"
    return "Minimalny"


def get_probability_for_location(payload: Any, latitude: float, longitude: float) -> Tuple[float, float, float]:
    """Zwraca (prawdopodobieństwo, najbliższa szerokość, najbliższa długość)."""
    punkty = extract_flat_points(payload)
    if punkty:
        cel_lon = normalize_longitude(longitude) % 360
        najblizszy = min(
            punkty, key=lambda p: _lon_distance(p[0], cel_lon) ** 2 + (p[1] - latitude) ** 2
        )
        lon, lat, wartosc = najblizszy
        return wartosc, lat, normalize_longitude(lon)

    latitudes, longitudes, grid = extract_ovation_grid(payload)

    if len(latitudes) == 0 or len(longitudes) == 0 or len(grid) == 0:
        raise ValueError("Brak danych do obliczenia prawdopodobieństwa.")

    lat_idx = nearest_index(latitudes, latitude)
    lon_idx = nearest_index(longitudes, normalize_longitude(longitude))

    # Jeśli siatka jest 2D (rows=lat, cols=lon): pobieramy odpowiedni element.
    if grid and isinstance(grid[0], list):
        row = grid[lat_idx] if lat_idx < len(grid) else grid[-1]
        val = row[lon_idx] if lon_idx < len(row) else row[-1]
        return float(val), float(latitudes[lat_idx]), float(longitudes[lon_idx])

    # Jeśli grid ma pojedynczy poziom, próbujemy użyć pierwszego elementu listy.
    if grid and isinstance(grid[0], (int, float)):
        return float(grid[0]), float(latitudes[lat_idx]), float(longitudes[lon_idx])

    # W najgorszym przypadku zwracamy 0.0.
    return 0.0, float(latitudes[lat_idx]), float(longitudes[lon_idx])


def top_probability_cells(payload: Any, limit: int = 5) -> List[Tuple[float, float, float]]:
    """Zwraca top N komórek z najwyższym prawdopodobieństwem z siatki OVATION."""
    punkty = extract_flat_points(payload)
    if punkty:
        najlepsze = sorted(punkty, key=lambda p: p[2], reverse=True)[:limit]
        return [(wartosc, lat, normalize_longitude(lon)) for lon, lat, wartosc in najlepsze]

    latitudes, longitudes, grid = extract_ovation_grid(payload)
    cells = []

    if not grid or not isinstance(grid[0], list):
        return []

    for lat_idx, lat in enumerate(latitudes):
        for lon_idx, lon in enumerate(longitudes):
            if lat_idx < len(grid) and lon_idx < len(grid[lat_idx]):
                probability = float(grid[lat_idx][lon_idx])
                cells.append((probability, float(lat), float(lon)))

    cells.sort(key=lambda item: item[0], reverse=True)
    return cells[:limit]


def parse_alerts(payload: Any) -> List[dict]:
    """Zwraca alerty zorzowe / geomagnetyczne z SWPC."""
    if payload is None:
        return []

    items: Iterable[Any]
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = payload.get("items") or payload.get("alerts") or [payload]
    else:
        items = [payload]

    alerts = []
    for item in items:
        if not isinstance(item, dict):
            continue

        message = (
            item.get("message")
            or item.get("text")
            or item.get("summary")
            or item.get("description")
            or item.get("detail")
            or ""
        )
        if not message:
            continue

        text = str(message).lower()
        if "aurora" not in text and "geomagnetic storm" not in text and "kp" not in text:
            continue

        alerts.append(
            {
                "event": item.get("event") or item.get("title") or "Aurora/Geomagnetic alert",
                "message": str(message),
                "issue_time": item.get("issue_time") or item.get("time_tag") or item.get("issued") or "brak",
                "severity": item.get("severity") or item.get("level") or "unknown",
            }
        )

    return alerts


def print_aurora_report(payload: Any, latitude: float, longitude: float, limit: int = 5) -> None:
    print("=" * 72)
    print("NOAA SWPC Aurora Monitor")
    print(f"Czas pobrania: {isoformat_utc(now_utc())}")
    print(f"Lokalizacja użytkownika: {latitude:.2f}°, {longitude:.2f}°")
    print("=" * 72)

    try:
        probability, nearest_lat, nearest_lon = get_probability_for_location(payload, latitude, longitude)
        print(f"Prawdopodobieństwo zorzy w Twojej lokalizacji: {probability:.1f}% ({probability_label(probability)})")
        print(f"Najbliższy punkt siatki: {nearest_lat:.2f}°, {nearest_lon:.2f}°")
    except Exception as exc:
        print(f"Nie udało się policzyć prawdopodobieństwa: {exc}")

    print("\nTop komórki z najwyższą aurorą:")
    try:
        cells = top_probability_cells(payload, limit=limit)
        if not cells:
            print("Brak danych siatki OVATION.")
        else:
            for idx, (probability, lat, lon) in enumerate(cells, start=1):
                print(f"  {idx}. {probability:5.1f}% | lat {lat:7.2f}° | lon {lon:7.2f}°")
    except Exception as exc:
        print(f"  Brak danych: {exc}")

    print("\nAlerty zorzowe / geomagnetyczne:")
    try:
        alerts = parse_alerts(fetch_json(ALERTS_URL))
        if not alerts:
            print("  Brak aktualnych alertów zorzowych lub geomagnetycznych.")
        else:
            for alert in alerts[:5]:
                issue = isoformat_utc(alert.get("issue_time"))
                print(f"  - {alert['event']} | {issue}")
                print(f"    {alert['message'][:220]}{'...' if len(alert['message']) > 220 else ''}")
    except Exception as exc:
        print(f"  Nie udało się pobrać alertów: {exc}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Monitor zorzy z NOAA SWPC")
    parser.add_argument("--lat", type=float, default=52.23, help="Szerokość geograficzna (np. 52.23)")
    parser.add_argument("--lon", type=float, default=21.01, help="Długość geograficzna (np. 21.01)")
    parser.add_argument("--limit", type=int, default=5, help="Ilość komórek do wyświetlenia w rankingu")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        payload = fetch_json(OVATION_URL)
        print_aurora_report(payload, args.lat, args.lon, limit=args.limit)
        return 0
    except Exception as exc:
        print(f"Błąd: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
