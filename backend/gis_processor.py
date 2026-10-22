"""
GIS and spatial geometry processing for ADAPTFIT.
Provides geospatial distance calculations and elevation gradient/slope determination.
"""
from typing import List, Tuple
import math


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Great-circle distance between two (lat, lon) coordinates in kilometres.
    """
    r = 6371.0  # Earth radius in km
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    )
    return 2.0 * r * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def get_slope_sampling_offsets(
    lat: float,
    lon: float,
    distance_m: float = 100.0,
) -> Tuple[List[float], List[float]]:
    """
    Calculate 5 coordinate sample points: [center, north, south, east, west]
    at a given offset distance in metres from the center point.
    1 degree of latitude is approximately 111,320 m.
    """
    delta_lat = distance_m / 111320.0
    lat_north = lat + delta_lat
    lat_south = lat - delta_lat

    cos_lat = math.cos(math.radians(lat))
    if abs(cos_lat) < 1e-6:
        cos_lat = 1e-6
    delta_lon = distance_m / (111320.0 * cos_lat)
    lon_east = lon + delta_lon
    lon_west = lon - delta_lon

    lats = [lat, lat_north, lat_south, lat, lat]
    lons = [lon, lon, lon, lon_east, lon_west]
    return lats, lons


def calculate_slope_from_elevations(
    z_center: float,
    z_north: float,
    z_south: float,
    z_east: float,
    z_west: float,
    distance_m: float = 100.0,
) -> float:
    """
    Calculate ground slope percentage from elevations using a 4-neighbour
    central difference gradient.
    dz_dx = (z_east - z_west) / (2 * distance_m)
    dz_dy = (z_north - z_south) / (2 * distance_m)
    gradient = sqrt(dz_dx^2 + dz_dy^2)
    slope_pct = round(gradient * 100.0, 1)
    """
    span_m = 2.0 * distance_m
    dz_dx = (z_east - z_west) / span_m
    dz_dy = (z_north - z_south) / span_m
    gradient = math.sqrt(dz_dx ** 2 + dz_dy ** 2)
    return round(gradient * 100.0, 1)
