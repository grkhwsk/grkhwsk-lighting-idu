"""
mask_s0.py
Формирование маски S0 и присвоение атрибутов активности ячейкам сетки.

Результат: data/interim/grid_s0.gpkg
  - Mask_S0: 1 если ячейка пересекает OOPZ или транспортный буфер (major/residential)
  - active_morning, active_day, active_evening, active_night: максимальное значение
    активности по всем OOPZ-объектам, пересекающим ячейку
  - source: 'oopz', 'transport', 'both', 'none'
  - activity_types: все типы активности через запятую
  - dominant_type: доминирующий тип активности
  - conflict_type: 'none', 'overlap', 'transport', 'both'
"""

import geopandas as gpd
import pandas as pd
from pathlib import Path

# ─────────────────────────────────────────
# ПУТИ К ФАЙЛАМ
# ─────────────────────────────────────────

BASE = Path(__file__).parent.parent  # корень репозитория

GRID = BASE / "data/interim/grid_25_aoi_1.gpkg"
OOPZ_POLY = BASE / "data/interim/facility_buffer_15_cut_buildings.gpkg"
OOPZ_SPACE = BASE / "data/interim/poi_polygons_rank_1_space.gpkg"
OOPZ_POINTS = BASE / "data/interim/poi_points_rank_1_buffer_cut.gpkg"
TRANSPORT = BASE / "data/interim/transport_buffer_all.gpkg"
ACTIVITY = BASE / "data/interim/activity_matrix.csv"
BUILDINGS = BASE / "data/processed/buildings.gpkg"
OUTPUT = BASE / "data/interim/grid_s0_1.gpkg"

# ─────────────────────────────────────────
# ПАРАМЕТРЫ
# ─────────────────────────────────────────

TRANSPORT_CLASSES = ["major", "residential"]
SLOTS = ["morning", "day", "evening", "night"]

PRIORITY = [
    "transit",
    "healthcare",
    "education",
    "child_activity",
    "administration_business",
    "services_retail",
    "sport",
    "recreation",
    "leisure_culture",
]

# ─────────────────────────────────────────
# ЗАГРУЗКА ДАННЫХ
# ─────────────────────────────────────────

print("Загрузка данных...")

grid = gpd.read_file(GRID)
transport = gpd.read_file(TRANSPORT)
activity = pd.read_csv(ACTIVITY)
buildings = gpd.read_file(BUILDINGS)

# Вычитаем здания из сетки
grid = grid[~grid.geometry.centroid.within(buildings.union_all())]
grid = grid.reset_index(drop=True)
print(f"  Сетка после вычитания зданий: {len(grid)} ячеек")

# Загружаем все OOPZ-слои и объединяем
oopz_parts = []
for path, label in [
    (OOPZ_POLY, "facility"),
    (OOPZ_SPACE, "space"),
    (OOPZ_POINTS, "points"),
]:
    if Path(path).exists():
        gdf = gpd.read_file(path)
        gdf["_source_layer"] = label
        oopz_parts.append(gdf)

oopz = pd.concat(oopz_parts, ignore_index=True)
oopz = gpd.GeoDataFrame(oopz, geometry="geometry", crs=oopz_parts[0].crs)

print(f"  Сетка: {len(grid)} ячеек")
print(f"  OOPZ объектов: {len(oopz)}")
print(f"  Транспортных буферов: {len(transport)}")

# ─────────────────────────────────────────
# ПРИВЕДЕНИЕ CRS
# ─────────────────────────────────────────

target_crs = grid.crs

for name, gdf in [("oopz", oopz), ("transport", transport)]:
    if gdf.crs != target_crs:
        print(f"  Перепроецирование {name}: {gdf.crs} → {target_crs}")

oopz = oopz.to_crs(target_crs)
transport = transport.to_crs(target_crs)

# ─────────────────────────────────────────
# JOIN МАТРИЦЫ АКТИВНОСТИ К OOPZ
# ─────────────────────────────────────────

print("Присвоение активности объектам OOPZ...")

oopz = oopz.merge(activity[["osm_value"] + SLOTS], on="osm_value", how="left")

for slot in SLOTS:
    oopz[slot] = oopz[slot].fillna(0).astype(int)

missing = oopz[oopz[SLOTS].sum(axis=1) == 0]["osm_value"].unique()
if len(missing) > 0:
    print(f"  Внимание: нет в матрице активности: {list(missing)}")

# ─────────────────────────────────────────
# МАСКА S0: ТРАНСПОРТ
# ─────────────────────────────────────────

print("Формирование транспортной маски...")

transport_need = transport[transport["road_class"].isin(TRANSPORT_CLASSES)].copy()
transport_need = transport_need.explode(index_parts=False).reset_index(drop=True)
transport_other = transport[~transport["road_class"].isin(TRANSPORT_CLASSES)].copy()

print(f"  В индексе (major/residential): {len(transport_need)} объектов")
print(f"  Исключено (local): {len(transport_other)} объектов")

grid_transport = gpd.sjoin(
    grid[["id", "geometry"]],
    transport_need[["geometry"]],
    how="left",
    predicate="intersects",
)
transport_mask = (
    grid_transport[grid_transport["index_right"].notna()]
    .groupby("id")
    .size()
    .reset_index(name="_transport_count")
)
transport_mask["mask_transport"] = 1

# ─────────────────────────────────────────
# МАСКА S0: OOPZ + АКТИВНОСТЬ
# ─────────────────────────────────────────

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

# Базовая агрегация
oopz_agg = (
    grid_oopz_typed.groupby("id")
    .agg(
        _oopz_count=("osm_value", "count"),
        active_morning=("morning", "max"),
        active_day=("day", "max"),
        active_evening=("evening", "max"),
        active_night=("night", "max"),
    )
    .reset_index()
)

# activity_types — все уникальные типы через запятую
activity_types_agg = (
    grid_oopz_typed.groupby("id")["activity_type"]
    .apply(lambda x: ", ".join(sorted(x.dropna().unique())))
    .reset_index()
)
activity_types_agg.columns = ["id", "activity_types"]


# dominant_type — тип с наибольшим числом активных слотов
def get_dominant(group):
    group = group.copy()
    group["slot_sum"] = (
        group["morning"] + group["day"] + group["evening"] + group["night"]
    )
    group["priority"] = group["activity_type"].apply(
        lambda x: PRIORITY.index(x) if x in PRIORITY else len(PRIORITY)
    )
    group = group.sort_values(["slot_sum", "priority"], ascending=[False, True])
    return group.iloc[0]["activity_type"] if len(group) > 0 else None


dominant = grid_oopz_typed.groupby("id").apply(get_dominant).reset_index()
dominant.columns = ["id", "dominant_type"]

# Присоединяем к агрегации
oopz_agg = oopz_agg.merge(activity_types_agg, on="id", how="left")
oopz_agg = oopz_agg.merge(dominant, on="id", how="left")
oopz_agg["mask_oopz"] = (oopz_agg["_oopz_count"] > 0).astype(int)

# ─────────────────────────────────────────
# СБОРКА ФИНАЛЬНОГО СЛОЯ
# ─────────────────────────────────────────

print("Сборка финального слоя grid_s0...")

result = grid[["id", "geometry"]].copy()

result = result.merge(
    oopz_agg[
        ["id", "mask_oopz", "_oopz_count", "activity_types", "dominant_type"]
        + [f"active_{s}" for s in SLOTS]
    ],
    on="id",
    how="left",
)
result = result.merge(transport_mask[["id", "mask_transport"]], on="id", how="left")

# Заполняем пропуски
result["mask_oopz"] = result["mask_oopz"].fillna(0).astype(int)
result["mask_transport"] = result["mask_transport"].fillna(0).astype(int)
result["_oopz_count"] = result["_oopz_count"].fillna(0).astype(int)

for slot in SLOTS:
    result[f"active_{slot}"] = result[f"active_{slot}"].fillna(0).astype(int)

# Итоговая маска S0
result["Mask_S0"] = (
    (result["mask_oopz"] == 1) | (result["mask_transport"] == 1)
).astype(int)

# Для транспортных ячеек без OOPZ — активность 1 во всех слотах
transport_only = (result["mask_transport"] == 1) & (result["mask_oopz"] == 0)
for slot in SLOTS:
    result.loc[transport_only, f"active_{slot}"] = 1


# Источник маски
def get_source(row):
    if row["mask_oopz"] == 1 and row["mask_transport"] == 1:
        return "both"
    elif row["mask_oopz"] == 1:
        return "oopz"
    elif row["mask_transport"] == 1:
        return "transport"
    else:
        return "none"


result["source"] = result.apply(get_source, axis=1)

# ─────────────────────────────────────────
# ЕДИНЫЙ АТРИБУТ КОНФЛИКТА
# ─────────────────────────────────────────
# overlap   — ≥2 OOPZ-объекта в одной ячейке (конфликт режимов активности)
# transport — ячейка одновременно в OOPZ и транспортном буфере (конфликт зон)
# both      — оба типа конфликта одновременно
# none      — конфликтов нет


def get_conflict_type(row):
    has_overlap = row["_oopz_count"] >= 2
    has_transport = row["source"] == "both"
    if has_overlap and has_transport:
        return "both"
    elif has_overlap:
        return "overlap"
    elif has_transport:
        return "transport"
    else:
        return "none"


result["conflict_type"] = result.apply(get_conflict_type, axis=1)

# ─────────────────────────────────────────
# СОХРАНЕНИЕ
# ─────────────────────────────────────────

result = gpd.GeoDataFrame(result, geometry="geometry", crs=target_crs)
result.to_file(OUTPUT, driver="GPKG")

# ─────────────────────────────────────────
# СТАТИСТИКА
# ─────────────────────────────────────────

total = len(result)
active = result["Mask_S0"].sum()
oopz_cells = result["mask_oopz"].sum()
trans_cells = result["mask_transport"].sum()
both_cells = (result["source"] == "both").sum()

ct = result["conflict_type"].value_counts()

print(f"\n── Результат ──────────────────────────")
print(f"  Всего ячеек:            {total}")
print(f"  Mask_S0 = 1:            {active} ({active/total*100:.1f}%)")
print(f"  Из них OOPZ:            {oopz_cells}")
print(f"  Из них транспорт:       {trans_cells}")
print(f"  Из них оба источника:   {both_cells}")
print(f"\n── Конфликты ──────────────────────────")
print(f"  overlap:                {ct.get('overlap', 0)}")
print(f"  transport:              {ct.get('transport', 0)}")
print(f"  both:                   {ct.get('both', 0)}")
print(f"  none:                   {ct.get('none', 0)}")
print(f"\nСохранено: {OUTPUT}")
