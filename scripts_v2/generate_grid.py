"""
generate_grid.py
Генерация гексагональной сетки для модели NeedIndex.

Запуск:
    python scripts/generate_grid.py --city norilsk
    python scripts/generate_grid.py --city polyarnye_zori

Алгоритм:
    1. Генерирует pointy-top гексагоны по bbox AOI
    2. Оставляет ячейки, чей центроид попадает внутрь AOI
    3. Исключает ячейки, чей центроид попадает на здание
    4. Присваивает последовательный id

Математика: при cell_size_m = d расстояние между центрами
соседних ячеек во всех шести направлениях равно d.
"""

import geopandas as gpd
import numpy as np
from shapely.geometry import Polygon
from utils import load_config, get_path

# ── Совместимость geopandas ───────────────────────────────────────

def union_geometries(gdf):
    """union_all() появился в geopandas 0.14; fallback на unary_union."""
    if hasattr(gdf, "union_all"):
        return gdf.union_all()
    return gdf.unary_union

# ── Конфиг ───────────────────────────────────────────────────────

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
aoi       = gpd.read_file(AOI_PATH).to_crs(CRS)
buildings = gpd.read_file(BLDG_PATH).to_crs(CRS)

if aoi.is_empty.all():
    raise ValueError(f"AOI пустой: {AOI_PATH}")

aoi_union  = union_geometries(aoi)
bldg_union = union_geometries(buildings)

print(f"  AOI: площадь ≈ {aoi.area.sum() / 1e6:.2f} км²")
print(f"  Зданий: {len(buildings)}")

# ── Генерация гексагонов ──────────────────────────────────────────
# Pointy-top ориентация (угол +30° от оси X).
# R — circumradius (центр → вершина).
# При R = cell_size / sqrt(3) расстояние между соседними центрами = cell_size.

R        = CELL_SIZE / np.sqrt(3)   # circumradius гексагона
col_step = 1.5 * R                  # горизонтальный шаг между колонками
row_step = CELL_SIZE                # вертикальный шаг внутри колонки
offset   = CELL_SIZE / 2           # смещение нечётных колонок


def make_hexagon(cx: float, cy: float, circumradius: float) -> Polygon:
    """Возвращает pointy-top гексагон с центром (cx, cy)."""
    angles = np.linspace(0, 2 * np.pi, 7)[:-1] + np.pi / 6
    xs = cx + circumradius * np.cos(angles)
    ys = cy + circumradius * np.sin(angles)
    return Polygon(zip(xs, ys))


minx, miny, maxx, maxy = aoi_union.bounds
# Запас в одну ячейку по периметру, чтобы не обрезать граничные ячейки
minx -= col_step;  miny -= row_step
maxx += col_step;  maxy += row_step

hexagons: list[Polygon] = []
col, x = 0, minx
while x <= maxx:
    y = miny + (offset if col % 2 == 1 else 0)
    while y <= maxy:
        hexagons.append(make_hexagon(x, y, R))
        y += row_step
    x += col_step
    col += 1

print(f"\n  Сгенерировано (до обрезки): {len(hexagons)} ячеек")

# ── Фильтрация ────────────────────────────────────────────────────

grid_raw = gpd.GeoDataFrame(geometry=hexagons, crs=CRS)

# Шаг 1: центроид внутри AOI
centroids = grid_raw.geometry.centroid
grid_aoi  = grid_raw[centroids.within(aoi_union)].copy().reset_index(drop=True)

# Шаг 2: центроид не на здании
centroids2 = grid_aoi.geometry.centroid
on_bldg    = centroids2.within(bldg_union)
grid_clean = grid_aoi[~on_bldg].copy().reset_index(drop=True)

print(f"  После обрезки по AOI:    {len(grid_aoi)} ячеек")
print(f"  После исключения зданий: {len(grid_clean)} ячеек "
      f"(исключено: {on_bldg.sum()})")

# ── Сохранение ────────────────────────────────────────────────────

grid_clean["id"] = range(1, len(grid_clean) + 1)
OUTPUT.parent.mkdir(parents=True, exist_ok=True)
grid_clean[["id", "geometry"]].to_file(OUTPUT, driver="GPKG")

print(f"\n── Результат ───────────────────────────")
print(f"  Итого ячеек: {len(grid_clean)}")
print(f"  Сохранено:   {OUTPUT}")