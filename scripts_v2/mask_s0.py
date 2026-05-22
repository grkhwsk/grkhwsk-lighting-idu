"""
mask_s0.py
Формирование маски S0 и присвоение атрибутов активности ячейкам сетки.

Запуск:
    python scripts/mask_s0.py --city norilsk
    python scripts/mask_s0.py --city polyarnye_zori

Выход: data/generated/grid_s0.gpkg
  - Mask_S0:       1 если ячейка пересекает OOPZ или транспортный буфер
  - active_<slot>: максимальная активность по всем OOPZ в ячейке
  - source:        'oopz' | 'transport' | 'both' | 'none'
  - activity_types: все типы активности через запятую
  - dominant_type:  доминирующий тип активности
  - conflict_type: 'overlap' | 'transport' | 'both' | 'none'
  - mask_24h:      1 если ячейка попадает в зону круглосуточной активности
"""

import geopandas as gpd
import numpy as np
import pandas as pd
from utils import load_config, get_path, get_shared_path

# ── Совместимость geopandas ───────────────────────────────────────

def union_geometries(gdf):
    """union_all() появился в geopandas 0.14; fallback на unary_union."""
    if hasattr(gdf, "union_all"):
        return gdf.union_all()
    return gdf.unary_union

# ── Конфиг ───────────────────────────────────────────────────────

config, BASE = load_config()

SLOTS             = list(config["slots"].keys())
TRANSPORT_CLASSES = list(config["buffers"]["transport"].keys())
TRANSPORT_CLASSES = [k for k in TRANSPORT_CLASSES if k != "local"]  # local в маску не входит

PRIORITY = [
    "transit", "healthcare", "education", "child_activity",
    "administration_business", "services_retail",
    "sport", "recreation", "leisure_culture",
]

# ── Пути ─────────────────────────────────────────────────────────

GRID      = get_path(config, BASE, "grid")
TRANSPORT = get_path(config, BASE, "transport")
ACTIVITY  = get_shared_path(config, BASE, "activity_matrix")
BUILDINGS = get_path(config, BASE, "buildings")
OUTPUT    = BASE / config["paths"]["data_generated"] / "grid_s0.gpkg"

OOPZ_SOURCES = [
    (get_path(config, BASE, "poi_facility_poly"),  "facility"),
    (get_path(config, BASE, "poi_facility_terr"),  "territory"),
    (get_path(config, BASE, "poi_space"),          "space"),
    (get_path(config, BASE, "poi_points"),         "points"),
]

# ── Загрузка данных ───────────────────────────────────────────────

print("Загрузка данных...")

grid      = gpd.read_file(GRID)
transport = gpd.read_file(TRANSPORT)
activity  = pd.read_csv(ACTIVITY)
buildings = gpd.read_file(BUILDINGS)

# Исключаем ячейки, чей центроид попадает на здание
bldg_union = union_geometries(buildings.to_crs(grid.crs))
grid = grid[~grid.geometry.centroid.within(bldg_union)].reset_index(drop=True)
print(f"  Сетка после вычитания зданий: {len(grid)} ячеек")

# Загружаем все OOPZ-слои
oopz_parts = []
for path, label in OOPZ_SOURCES:
    if path.exists():
        gdf = gpd.read_file(path)
        gdf["_source_layer"] = label
        oopz_parts.append(gdf)
    else:
        print(f"  Внимание: слой не найден — {path.name}")

if not oopz_parts:
    raise FileNotFoundError("Не найден ни один OOPZ-слой. Проверьте config.yaml → layers.")

oopz = gpd.GeoDataFrame(
    pd.concat(oopz_parts, ignore_index=True),
    geometry="geometry",
    crs=oopz_parts[0].crs,
)

print(f"  Сетка:            {len(grid)} ячеек")
print(f"  OOPZ объектов:    {len(oopz)}")
print(f"  Транспортных буферов: {len(transport)}")

# ── Приведение CRS ────────────────────────────────────────────────

target_crs = grid.crs
oopz       = oopz.to_crs(target_crs)
transport  = transport.to_crs(target_crs)

# ── Матрица активности → OOPZ ─────────────────────────────────────

print("Присвоение активности объектам OOPZ...")

oopz = oopz.merge(activity[["osm_value"] + SLOTS], on="osm_value", how="left")
for slot in SLOTS:
    oopz[slot] = oopz[slot].fillna(0).astype(int)

missing = oopz[oopz[SLOTS].sum(axis=1) == 0]["osm_value"].unique()
if len(missing) > 0:
    print(f"  Внимание: нет в матрице активности: {list(missing)}")

# ── Транспортная маска ────────────────────────────────────────────

print("Формирование транспортной маски...")

transport_need  = transport[transport["road_class"].isin(TRANSPORT_CLASSES)].copy()
transport_need  = transport_need.explode(index_parts=False).reset_index(drop=True)
transport_other = transport[~transport["road_class"].isin(TRANSPORT_CLASSES)]

print(f"  В индексе ({'/'.join(TRANSPORT_CLASSES)}): {len(transport_need)} объектов")
print(f"  Исключено (local): {len(transport_other)} объектов")

grid_transport = gpd.sjoin(
    grid[["id", "geometry"]],
    transport_need[["geometry"]],
    how="left",
    predicate="intersects",
)
transport_mask = (
    grid_transport[grid_transport["index_right"].notna()]
    .groupby("id").size().reset_index(name="_transport_count")
)
transport_mask["mask_transport"] = 1

# ── OOPZ-маска и агрегация активности ────────────────────────────

print("Формирование маски OOPZ и агрегация активности...")

grid_oopz = gpd.sjoin(
    grid[["id", "geometry"]],
    oopz[["geometry", "osm_value"] + SLOTS],
    how="left",
    predicate="intersects",
)
grid_oopz_typed = grid_oopz[grid_oopz["index_right"].notna()].copy()
grid_oopz_typed = grid_oopz_typed.merge(
    oopz[["activity_type"]], left_on="index_right", right_index=True, how="left"
)

# Базовая агрегация активности по слотам
oopz_agg = (
    grid_oopz_typed.groupby("id")
    .agg(
        _oopz_count=("osm_value", "count"),
        **{f"active_{s}": (s, "max") for s in SLOTS},
    )
    .reset_index()
)

# Все типы активности через запятую
activity_types_agg = (
    grid_oopz_typed.groupby("id")["activity_type"]
    .apply(lambda x: ", ".join(sorted(x.dropna().unique())))
    .reset_index(name="activity_types")
)

# Доминирующий тип: максимальный slot_sum, при равенстве — по приоритету
def get_dominant(group):
    group = group.copy()
    group["slot_sum"]  = group[SLOTS].sum(axis=1)   # динамически по конфигу
    group["priority"]  = group["activity_type"].apply(
        lambda x: PRIORITY.index(x) if x in PRIORITY else len(PRIORITY)
    )
    group = group.sort_values(["slot_sum", "priority"], ascending=[False, True])
    return group.iloc[0]["activity_type"] if len(group) > 0 else None

dominant = grid_oopz_typed.groupby("id").apply(get_dominant).reset_index()
dominant.columns = ["id", "dominant_type"]

oopz_agg = oopz_agg.merge(activity_types_agg, on="id", how="left")
oopz_agg = oopz_agg.merge(dominant, on="id", how="left")
oopz_agg["mask_oopz"] = (oopz_agg["_oopz_count"] > 0).astype(int)

# ── Сборка результата ─────────────────────────────────────────────

print("Сборка финального слоя grid_s0...")

result = grid[["id", "geometry"]].copy()
result = result.merge(
    oopz_agg[
        ["id", "mask_oopz", "_oopz_count", "activity_types", "dominant_type"]
        + [f"active_{s}" for s in SLOTS]
    ],
    on="id", how="left",
)
result = result.merge(transport_mask[["id", "mask_transport"]], on="id", how="left")

result["mask_oopz"]      = result["mask_oopz"].fillna(0).astype(int)
result["mask_transport"] = result["mask_transport"].fillna(0).astype(int)
result["_oopz_count"]    = result["_oopz_count"].fillna(0).astype(int)
for slot in SLOTS:
    result[f"active_{slot}"] = result[f"active_{slot}"].fillna(0).astype(int)

result["Mask_S0"] = (
    (result["mask_oopz"] == 1) | (result["mask_transport"] == 1)
).astype(int)

# Транспортные ячейки без OOPZ — активны во всех слотах
transport_only = (result["mask_transport"] == 1) & (result["mask_oopz"] == 0)
for slot in SLOTS:
    result.loc[transport_only, f"active_{slot}"] = 1

# Источник маски — векторизовано вместо apply()
result["source"] = np.select(
    [
        (result["mask_oopz"] == 1) & (result["mask_transport"] == 1),
        result["mask_oopz"] == 1,
        result["mask_transport"] == 1,
    ],
    ["both", "oopz", "transport"],
    default="none",
)

# ── Конфликты — векторизовано вместо apply() ─────────────────────
# overlap:   ≥2 OOPZ-объекта в одной ячейке
# transport: ячейка одновременно в OOPZ и транспортном буфере
# both:      оба типа конфликта

has_overlap   = result["_oopz_count"] >= 2
has_transport = result["source"] == "both"

result["conflict_type"] = np.select(
    [has_overlap & has_transport, has_overlap, has_transport],
    ["both", "overlap", "transport"],
    default="none",
)

# ── Маска 24h ─────────────────────────────────────────────────────
# mask_24h = 1 для ячеек в зоне объектов с активностью во всех слотах
# или в буфере дорог major/residential

print("Формирование маски 24h...")

oopz_24h = oopz[(oopz[SLOTS] == 1).all(axis=1)].copy()
print(f"  24h объектов OOPZ: {len(oopz_24h)}")
if len(oopz_24h) > 0:
    print(f"  Типы: {oopz_24h['activity_type'].value_counts().to_dict()}")

transport_24h = transport[transport["road_class"].isin(TRANSPORT_CLASSES)].copy()

mask_24h_ids = set()

if len(oopz_24h) > 0:
    join_24h = gpd.sjoin(
        grid[["id", "geometry"]],
        oopz_24h[["geometry"]],
        how="inner",
        predicate="intersects",
    )
    mask_24h_ids.update(join_24h["id"].unique())
    print(f"  Ячеек от 24h объектов: {len(join_24h['id'].unique())}")

if len(transport_24h) > 0:
    join_tr = gpd.sjoin(
        grid[["id", "geometry"]],
        transport_24h.explode(index_parts=False)[["geometry"]],
        how="inner",
        predicate="intersects",
    )
    mask_24h_ids.update(join_tr["id"].unique())
    print(f"  Ячеек от транспорта:   {len(join_tr['id'].unique())}")

result["mask_24h"] = result["id"].isin(mask_24h_ids).astype(int)
print(f"  Итого mask_24h = 1: {result['mask_24h'].sum()} ячеек")

# ── Сохранение ────────────────────────────────────────────────────

result = gpd.GeoDataFrame(result, geometry="geometry", crs=target_crs)
OUTPUT.parent.mkdir(parents=True, exist_ok=True)
result.to_file(OUTPUT, driver="GPKG")

# ── Статистика ────────────────────────────────────────────────────

total      = len(result)
active     = result["Mask_S0"].sum()
oopz_cells = result["mask_oopz"].sum()
tr_cells   = result["mask_transport"].sum()
both_cells = (result["source"] == "both").sum()
ct         = result["conflict_type"].value_counts()

print(f"\n── Результат ──────────────────────────")
print(f"  Всего ячеек:           {total}")
print(f"  Mask_S0 = 1:           {active} ({active / total * 100:.1f}%)")
print(f"  Из них OOPZ:           {oopz_cells}")
print(f"  Из них транспорт:      {tr_cells}")
print(f"  Из них оба источника:  {both_cells}")
print(f"\n── Конфликты ──────────────────────────")
for kind in ["overlap", "transport", "both", "none"]:
    print(f"  {kind:<12} {ct.get(kind, 0)}")
print(f"\nСохранено: {OUTPUT}")