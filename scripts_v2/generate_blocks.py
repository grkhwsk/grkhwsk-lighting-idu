"""
generate_blocks.py
Генерация кварталов методом полигонизации транспортного каркаса.

Алгоритм:
    1. Берёт дороги классов major и residential
    2. Буферизует и строит скелет для получения линий-разделителей
    3. Полигонизирует вместе с границей AOI
    4. Фильтрует по площади и периметру

Запуск:
    python scripts/generate_blocks.py --city norilsk
    python scripts/generate_blocks.py --city polyarnye_zori

Выход: data/generated/blocks_raw.gpkg
"""

import geopandas as gpd
from shapely.ops import polygonize, unary_union
from utils import load_config, get_path

# ── Совместимость geopandas ───────────────────────────────────────

def union_geometries(gdf):
    """union_all() появился в geopandas 0.14; fallback на unary_union."""
    if hasattr(gdf, "union_all"):
        return gdf.union_all()
    return gdf.unary_union

# ── Конфиг ───────────────────────────────────────────────────────

config, BASE = load_config()

CRS           = config["location"]["crs"]
BLOCK_FILTERS = config.get("blocks_generation", {})
MIN_AREA      = BLOCK_FILTERS.get("min_area_m2",   10000)
MAX_PERIMETER = BLOCK_FILTERS.get("max_perimeter_m", 20000)
ROAD_CLASSES  = config["buffers"]["transport"]
ROAD_CLASSES  = [k for k in ROAD_CLASSES if k != "local"]

ROADS_PATH = get_path(config, BASE, "roads_clean")
AOI_PATH   = get_path(config, BASE, "aoi")
OUTPUT     = BASE / config["paths"]["data_generated"] / "blocks_raw.gpkg"

print(f"  Классы дорог:  {ROAD_CLASSES}")
print(f"  Мин. площадь:  {MIN_AREA} м²")
print(f"  Макс. периметр: {MAX_PERIMETER} м")

# ── Загрузка данных ───────────────────────────────────────────────

print("\nЗагрузка данных...")

for path in (ROADS_PATH, AOI_PATH):
    if not path.exists():
        raise FileNotFoundError(
            f"Файл не найден: {path}\n"
            f"Проверьте config.yaml → layers"
        )

roads = gpd.read_file(ROADS_PATH).to_crs(CRS)
aoi   = gpd.read_file(AOI_PATH).to_crs(CRS)

print(f"  Дорог загружено: {len(roads)}")

aoi_geom = union_geometries(aoi)

# ── Построение кварталов ──────────────────────────────────────────

print("Полигонизация...")

barriers = roads[roads["road_class"].isin(ROAD_CLASSES)]
print(f"  Барьерных дорог ({'/'.join(ROAD_CLASSES)}): {len(barriers)}")

merged          = union_geometries(barriers)
merged_buffered = merged.buffer(6)
merged_skeleton = merged_buffered.buffer(-5)
boundary        = merged_skeleton.boundary

all_lines = unary_union([boundary, aoi_geom.boundary])
blocks    = list(polygonize(all_lines))

print(f"  Полигонов до фильтрации: {len(blocks)}")

# ── Фильтрация ────────────────────────────────────────────────────

blocks_gdf = gpd.GeoDataFrame(geometry=blocks, crs=CRS)
blocks_gdf["area_m2"]   = blocks_gdf.area.round(0)
blocks_gdf["perimeter"] = blocks_gdf.length.round(0)

blocks_clean = blocks_gdf[
    (blocks_gdf["area_m2"]   > MIN_AREA) &
    (blocks_gdf["perimeter"] < MAX_PERIMETER)
].reset_index(drop=True)

blocks_clean["block_id"] = blocks_clean.index + 1

print(f"  После фильтрации: {len(blocks_clean)} кварталов")
print(blocks_clean[["area_m2", "perimeter"]].describe().round(0))

# ── Сохранение ────────────────────────────────────────────────────

OUTPUT.parent.mkdir(parents=True, exist_ok=True)
blocks_clean.to_file(OUTPUT, driver="GPKG")

print(f"\nСохранено: {OUTPUT}")