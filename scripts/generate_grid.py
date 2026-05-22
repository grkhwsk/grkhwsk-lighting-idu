"""
generate_grid.py
Генерация гексагональной сетки для модели NeedIndex.

Запуск:
    python scripts/generate_grid.py --city norilsk
    python scripts/generate_grid.py --city polyarnye_zori
"""

import geopandas as gpd
import numpy as np
from pathlib import Path
from shapely.geometry import Polygon
from utils import load_config, get_path

config, BASE = load_config()

CELL_SIZE = config["grid"]["cell_size_m"]
CRS       = config["location"]["crs"]
AOI_PATH  = get_path(config, BASE, "aoi")
BLDG_PATH = get_path(config, BASE, "buildings")
OUTPUT    = get_path(config, BASE, "grid")

print(f"  Проекция:  {CRS}")
print(f"  Шаг сетки: {CELL_SIZE} м")

# ── Загрузка данных ───────────────────────────────────────────────

print("\nЗагрузка данных...")
aoi        = gpd.read_file(AOI_PATH).to_crs(CRS)
buildings  = gpd.read_file(BLDG_PATH).to_crs(CRS)
aoi_union  = aoi.union_all()
bldg_union = buildings.union_all()
print(f"  AOI: площадь ≈ {aoi.area.sum()/1e6:.2f} км²")
print(f"  Зданий: {len(buildings)}")

# ── Генерация гексагонов ──────────────────────────────────────────

R        = CELL_SIZE / np.sqrt(3)
col_step = 1.5 * R
row_step = CELL_SIZE
offset   = CELL_SIZE / 2


def make_hexagon(cx, cy, radius):
    angles = np.linspace(0, 2 * np.pi, 7)[:-1]
    angles += np.pi / 6
    return Polygon(zip(cx + radius * np.cos(angles), cy + radius * np.sin(angles)))


minx, miny, maxx, maxy = aoi_union.bounds
minx -= col_step;  miny -= row_step
maxx += col_step;  maxy += row_step

hexagons, col, x = [], 0, minx
while x <= maxx:
    y = miny + (offset if col % 2 == 1 else 0)
    while y <= maxy:
        hexagons.append(make_hexagon(x, y, R))
        y += row_step
    x += col_step
    col += 1

print(f"\n  Сгенерировано (до обрезки): {len(hexagons)} ячеек")

# ── Фильтрация ────────────────────────────────────────────────────

grid_raw   = gpd.GeoDataFrame(geometry=hexagons, crs=CRS)
centroids  = grid_raw.geometry.centroid
grid_aoi   = grid_raw[centroids.within(aoi_union)].copy().reset_index(drop=True)
centroids2 = grid_aoi.geometry.centroid
on_bldg    = centroids2.within(bldg_union)
grid_clean = grid_aoi[~on_bldg].copy().reset_index(drop=True)

print(f"  После обрезки по AOI:    {len(grid_aoi)} ячеек")
print(f"  После исключения зданий: {len(grid_clean)} ячеек")

# ── Сохранение ────────────────────────────────────────────────────

grid_clean["id"] = range(1, len(grid_clean) + 1)
OUTPUT.parent.mkdir(parents=True, exist_ok=True)
grid_clean[["id", "geometry"]].to_file(OUTPUT, driver="GPKG")

print(f"\n── Результат ───────────────────────────")
print(f"  Итого ячеек: {len(grid_clean)}")
print(f"  Сохранено:   {OUTPUT}")