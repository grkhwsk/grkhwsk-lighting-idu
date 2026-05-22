"""
zone_stats.py
Статистика по зонам территории AOI.

Запуск:
    python scripts/zone_stats.py --city norilsk
    python scripts/zone_stats.py --city polyarnye_zori

Требуемые слои в config.yaml → layers:
    grid             — сетка с маской S0 (после mask_s0.py)
    zones            — функциональные зоны ПЗЗ
    poi_raw_poly     — полный полигональный слой POI (все ранги, до буферизации)
    poi_raw_points   — полный точечный слой POI (все ранги, до буферизации)

Результат (в output/):
    zone_stats.csv           — сводная таблица по зонам
    zone_activity_detail.csv — типы активности по зонам (ячейки сетки)
    zone_objects.csv         — количество объектов POI по зонам, типам и рангам
"""

import geopandas as gpd
import pandas as pd
from utils import load_config, get_path, get_output_dir

# ── Конфиг ───────────────────────────────────────────────────────

config, BASE = load_config()

INTERIM_DIR = BASE / config["paths"]["data_generated"]
OUTPUT_DIR  = get_output_dir(config, BASE)

GRID_S0    = INTERIM_DIR / "grid_s0.gpkg"
ZONES      = get_path(config, BASE, "zones")
OOPZ_POLY  = get_path(config, BASE, "poi_raw_poly")
OOPZ_POINT = get_path(config, BASE, "poi_raw_points")

OUTPUT          = OUTPUT_DIR / "zone_stats.csv"
OUTPUT_ACTIVITY = OUTPUT_DIR / "zone_activity_detail.csv"
OUTPUT_OBJECTS  = OUTPUT_DIR / "zone_objects.csv"

# ── Загрузка данных ───────────────────────────────────────────────

print("Загрузка данных...")

for path in (GRID_S0, ZONES, OOPZ_POLY, OOPZ_POINT):
    if not path.exists():
        raise FileNotFoundError(
            f"Файл не найден: {path}\n"
            f"Проверьте config.yaml → layers и наличие исходных данных."
        )

grid  = gpd.read_file(GRID_S0)
zones = gpd.read_file(ZONES).to_crs(grid.crs)

print(f"  Ячеек сетки:  {len(grid)}")
print(f"  Зон:          {len(zones)}")

poly  = gpd.read_file(OOPZ_POLY).to_crs(grid.crs)
point = gpd.read_file(OOPZ_POINT).to_crs(grid.crs)

poly["_layer"]  = "polygon"
point["_layer"] = "point"

# Проверка обязательных колонок
required_cols = {"osm_value", "activity_type", "rank"}
for name, gdf in [("poi_raw_poly", poly), ("poi_raw_points", point)]:
    missing = required_cols - set(gdf.columns)
    if missing:
        raise KeyError(f"В слое {name} нет колонок: {sorted(missing)}")

# osm_id опционально — добавим если отсутствует
for gdf in (poly, point):
    if "osm_id" not in gdf.columns:
        gdf["osm_id"] = None

cols = ["osm_id", "osm_value", "activity_type", "rank", "_layer", "geometry"]
oopz_all = gpd.GeoDataFrame(
    pd.concat([poly[cols], point[cols]], ignore_index=True),
    geometry="geometry",
    crs=grid.crs,
)

print(f"  Объектов POI всего: {len(oopz_all)}")
print(f"  Из них rank 1:      {(oopz_all['rank'] == 1).sum()}")
print(f"  Из них rank 0:      {(oopz_all['rank'] == 0).sum()}")

# ── Пересечение сетки с зонами ────────────────────────────────────

print("Пересечение сетки с зонами...")

grid_c = grid.copy()
grid_c["geometry"] = grid_c.geometry.centroid

grid_zoned = gpd.sjoin(
    grid_c[["id", "Mask_S0", "mask_oopz", "mask_transport",
            "source", "dominant_type", "activity_types",
            "conflict_type", "_oopz_count", "geometry"]],
    zones[["zone_group", "zone_code", "geometry"]],
    how="left",
    predicate="within",
)
grid_zoned["zone_group"] = grid_zoned["zone_group"].fillna("Outside")
grid_zoned["zone_code"]  = grid_zoned["zone_code"].fillna("—")

print(f"  Ячеек с зоной: {(grid_zoned['zone_group'] != 'Outside').sum()}")
print(f"  Ячеек вне зон: {(grid_zoned['zone_group'] == 'Outside').sum()}")

# ── Пересечение POI с зонами ──────────────────────────────────────

print("Пересечение объектов POI с зонами...")

oopz_c = oopz_all.copy()
oopz_c["geometry"] = oopz_c.geometry.centroid

oopz_zoned = gpd.sjoin(
    oopz_c,
    zones[["zone_group", "geometry"]],
    how="left",
    predicate="within",
)
oopz_zoned["zone_group"] = oopz_zoned["zone_group"].fillna("Outside")

print(f"  Объектов с зоной: {(oopz_zoned['zone_group'] != 'Outside').sum()}")
print(f"  Объектов вне зон: {(oopz_zoned['zone_group'] == 'Outside').sum()}")

# ── Сводная таблица ───────────────────────────────────────────────

print("Расчёт статистики...")

zone_groups = sorted(grid_zoned["zone_group"].unique())
summary_rows = []

for zone in zone_groups:
    zdf      = grid_zoned[grid_zoned["zone_group"] == zone]
    zone_obj = oopz_zoned[oopz_zoned["zone_group"] == zone]
    total    = len(zdf)

    oopz_zdf = zdf[zdf["mask_oopz"] == 1]
    dominant = (
        oopz_zdf["dominant_type"].value_counts().index[0]
        if len(oopz_zdf) > 0 and oopz_zdf["dominant_type"].notna().any()
        else "—"
    )

    conf_overlap   = int((zdf["conflict_type"] == "overlap").sum())
    conf_transport = int((zdf["conflict_type"] == "transport").sum())
    conf_both      = int((zdf["conflict_type"] == "both").sum())

    summary_rows.append({
        "zone_group":         zone,
        "total_cells":        total,
        "mask_s0_cells":      int(zdf["Mask_S0"].sum()),
        "mask_s0_pct":        round(zdf["Mask_S0"].sum() / total * 100, 1) if total > 0 else 0,
        "oopz_cells":         int(zdf["mask_oopz"].sum()),
        "transport_cells":    int(zdf["mask_transport"].sum()),
        "both_cells":         int((zdf["source"] == "both").sum()),
        "oopz_objects_total": len(zone_obj),
        "oopz_rank1":         int((zone_obj["rank"] == 1).sum()),
        "oopz_rank0":         int((zone_obj["rank"] == 0).sum()),
        "conflict_total":     conf_overlap + conf_transport + conf_both,
        "conflict_overlap":   conf_overlap,
        "conflict_transport": conf_transport,
        "conflict_both":      conf_both,
        "dominant_type":      dominant,
    })

summary_df = pd.DataFrame(summary_rows)

# ── Детальная таблица: ячейки по типам активности ────────────────

activity_rows = []
oopz_grid = grid_zoned[grid_zoned["mask_oopz"] == 1]

for zone in zone_groups:
    zdf = oopz_grid[oopz_grid["zone_group"] == zone]
    if len(zdf) == 0:
        continue
    for act_type, count in zdf["dominant_type"].value_counts().items():
        activity_rows.append({
            "zone_group":    zone,
            "activity_type": act_type if pd.notna(act_type) else "не определён",
            "oopz_cells":    int(count),
        })

activity_df = pd.DataFrame(activity_rows)

# ── Таблица объектов по зонам/типам/рангам ────────────────────────

object_rows = []

for zone in zone_groups:
    zone_obj = oopz_zoned[oopz_zoned["zone_group"] == zone]
    if len(zone_obj) == 0:
        continue
    by_activity = zone_obj.groupby("activity_type").size().reset_index(name="total")
    for _, row in by_activity.iterrows():
        act    = row["activity_type"] if pd.notna(row["activity_type"]) else "не определён"
        subset = zone_obj[zone_obj["activity_type"] == row["activity_type"]]
        object_rows.append({
            "zone_group":    zone,
            "activity_type": act,
            "total":         int(row["total"]),
            "rank_1":        int((subset["rank"] == 1).sum()),
            "rank_0":        int((subset["rank"] == 0).sum()),
            "polygon":       int((subset["_layer"] == "polygon").sum()),
            "point":         int((subset["_layer"] == "point").sum()),
        })

objects_df = pd.DataFrame(object_rows)

# ── Сохранение ────────────────────────────────────────────────────

summary_df.to_csv(OUTPUT,          index=False, encoding="utf-8-sig")
activity_df.to_csv(OUTPUT_ACTIVITY, index=False, encoding="utf-8-sig")
objects_df.to_csv(OUTPUT_OBJECTS,  index=False, encoding="utf-8-sig")

# ── Вывод в консоль ───────────────────────────────────────────────

W = 82

def section_header(title: str):
    print(f"\n{'─' * W}")
    print(f"{title:^{W}}")
    print(f"{'─' * W}")

section_header("СВОДНАЯ СТАТИСТИКА ПО ЗОНАМ")
print(f"{'Зона':<22} {'Ячеек':>7} {'Mask_S0':>9} {'%':>6} "
      f"{'Всего':>7} {'rank1':>7} {'rank0':>7} {'Конфл.':>8}")
print(f"{'─' * W}")
for _, row in summary_df.iterrows():
    print(
        f"{row['zone_group']:<22} {row['total_cells']:>7} "
        f"{row['mask_s0_cells']:>9} {row['mask_s0_pct']:>5.1f}% "
        f"{row['oopz_objects_total']:>7} {row['oopz_rank1']:>7} "
        f"{row['oopz_rank0']:>7} {row['conflict_total']:>8}"
    )

section_header("ОБЪЕКТЫ POI ПО ЗОНАМ И ТИПАМ АКТИВНОСТИ")
print(f"{'Зона':<22} {'Тип активности':<26} {'Всего':>6} "
      f"{'rank1':>7} {'rank0':>7} {'polygon':>9} {'point':>7}")
print(f"{'─' * W}")
prev_zone = None
for zone in zone_groups:
    zone_data = objects_df[objects_df["zone_group"] == zone].sort_values("total", ascending=False)
    for _, row in zone_data.iterrows():
        zone_label = zone if zone != prev_zone else ""
        print(
            f"{zone_label:<22} {row['activity_type']:<26} "
            f"{row['total']:>6} {row['rank_1']:>7} {row['rank_0']:>7} "
            f"{row['polygon']:>9} {row['point']:>7}"
        )
        prev_zone = zone

section_header("КОНФЛИКТЫ ПО ЗОНАМ")
print(f"{'Зона':<22} {'Всего':>7} {'overlap':>10} {'transport':>12} {'both':>7}")
print(f"{'─' * W}")
for _, row in summary_df.iterrows():
    if row["conflict_total"] > 0:
        print(
            f"{row['zone_group']:<22} {row['conflict_total']:>7} "
            f"{row['conflict_overlap']:>10} {row['conflict_transport']:>12} "
            f"{row['conflict_both']:>7}"
        )

print(f"\nСохранено:")
print(f"  {OUTPUT}")
print(f"  {OUTPUT_ACTIVITY}")
print(f"  {OUTPUT_OBJECTS}")