"""
zone_stats.py
Статистика по зонам территории AOI.

Считается один раз на основе grid_s0.gpkg, zones.gpkg и полных OOPZ-слоёв с рангами.
Результат:
  - output/zone_stats.csv           — сводная таблица по зонам
  - output/zone_activity_detail.csv — типы активности по зонам (ячейки сетки)
  - output/zone_objects.csv         — количество объектов OOPZ по зонам, типам и рангам
"""

import geopandas as gpd
import pandas as pd
from pathlib import Path

# ─────────────────────────────────────────
# ПУТИ К ФАЙЛАМ
# ─────────────────────────────────────────

BASE    = Path(__file__).parent.parent
GRID_S0 = BASE / "data/interim/grid_s0_1.gpkg"
ZONES   = BASE / "data/processed/zones.gpkg"

# Полные слои OOPZ с рангами (rank 0 и rank 1)
OOPZ_POLY  = BASE / "data/interim/poi_polygons_merged_refactor_clean_with_ranks.gpkg"
OOPZ_POINT = BASE / "data/interim/poi_point_merged_refactor_clean_without_doubles__With_ranks.gpkg"

OUTPUT          = BASE / "output/zone_stats.csv"
OUTPUT_ACTIVITY = BASE / "output/zone_activity_detail.csv"
OUTPUT_OBJECTS  = BASE / "output/zone_objects.csv"

# ─────────────────────────────────────────
# ЗАГРУЗКА ДАННЫХ
# ─────────────────────────────────────────

print("Загрузка данных...")

grid  = gpd.read_file(GRID_S0)
zones = gpd.read_file(ZONES).to_crs(grid.crs)

print(f"  Ячеек сетки:  {len(grid)}")
print(f"  Зон:          {len(zones)}")

# Загружаем полные OOPZ-слои
poly  = gpd.read_file(OOPZ_POLY).to_crs(grid.crs)
point = gpd.read_file(OOPZ_POINT).to_crs(grid.crs)

poly["_layer"]  = "polygon"
point["_layer"] = "point"

# Объединяем в единый слой
cols = ["osm_id", "osm_value", "activity_type", "rank", "_layer", "geometry"]
oopz_all = pd.concat([
    poly[cols],
    point[cols]
], ignore_index=True)
oopz_all = gpd.GeoDataFrame(oopz_all, geometry="geometry", crs=grid.crs)

print(f"  Объектов OOPZ всего:   {len(oopz_all)}")
print(f"  Из них rank 1:         {(oopz_all['rank'] == 1).sum()}")
print(f"  Из них rank 0:         {(oopz_all['rank'] == 0).sum()}")

# ─────────────────────────────────────────
# ПЕРЕСЕЧЕНИЕ СЕТКИ С ЗОНАМИ
# ─────────────────────────────────────────

print("Пересечение сетки с зонами...")

grid_centroids = grid.copy()
grid_centroids["geometry"] = grid_centroids.geometry.centroid

grid_zoned = gpd.sjoin(
    grid_centroids[["id", "Mask_S0", "mask_oopz", "mask_transport",
                    "source", "dominant_type", "activity_types",
                    "conflict_type", "_oopz_count", "geometry"]],
    zones[["zone_group", "zone_code", "geometry"]],
    how="left",
    predicate="within"
)

grid_zoned["zone_group"] = grid_zoned["zone_group"].fillna("Outside")
grid_zoned["zone_code"]  = grid_zoned["zone_code"].fillna("—")

print(f"  Ячеек с зоной:  {(grid_zoned['zone_group'] != 'Outside').sum()}")
print(f"  Ячеек вне зон:  {(grid_zoned['zone_group'] == 'Outside').sum()}")

# ─────────────────────────────────────────
# ПЕРЕСЕЧЕНИЕ ОБЪЕКТОВ OOPZ С ЗОНАМИ
# ─────────────────────────────────────────

print("Пересечение объектов OOPZ с зонами...")

oopz_centroids = oopz_all.copy()
oopz_centroids["geometry"] = oopz_centroids.geometry.centroid

oopz_zoned = gpd.sjoin(
    oopz_centroids,
    zones[["zone_group", "geometry"]],
    how="left",
    predicate="within"
)
oopz_zoned["zone_group"] = oopz_zoned["zone_group"].fillna("Outside")

print(f"  Объектов с зоной:  {(oopz_zoned['zone_group'] != 'Outside').sum()}")
print(f"  Объектов вне зон:  {(oopz_zoned['zone_group'] == 'Outside').sum()}")

# ─────────────────────────────────────────
# СВОДНАЯ ТАБЛИЦА ПО ЗОНАМ
# ─────────────────────────────────────────

print("Расчёт статистики...")

zone_groups = sorted(grid_zoned["zone_group"].unique())
summary_rows = []

for zone in zone_groups:
    zdf      = grid_zoned[grid_zoned["zone_group"] == zone]
    zone_obj = oopz_zoned[oopz_zoned["zone_group"] == zone]

    total_cells   = len(zdf)
    mask_cells    = int(zdf["Mask_S0"].sum())
    oopz_cells    = int(zdf["mask_oopz"].sum())
    transp_cells  = int(zdf["mask_transport"].sum())
    both_cells    = int((zdf["source"] == "both").sum())

    conf_overlap   = int((zdf["conflict_type"] == "overlap").sum())
    conf_transport = int((zdf["conflict_type"] == "transport").sum())
    conf_both      = int((zdf["conflict_type"] == "both").sum())
    conf_total     = conf_overlap + conf_transport + conf_both

    oopz_zdf = zdf[zdf["mask_oopz"] == 1]
    dominant = (
        oopz_zdf["dominant_type"].value_counts().index[0]
        if len(oopz_zdf) > 0 and oopz_zdf["dominant_type"].notna().any()
        else "—"
    )

    summary_rows.append({
        "zone_group":         zone,
        "total_cells":        total_cells,
        "mask_s0_cells":      mask_cells,
        "mask_s0_pct":        round(mask_cells / total_cells * 100, 1) if total_cells > 0 else 0,
        "oopz_cells":         oopz_cells,
        "transport_cells":    transp_cells,
        "both_cells":         both_cells,
        "oopz_objects_total": len(zone_obj),
        "oopz_rank1":         int((zone_obj["rank"] == 1).sum()),
        "oopz_rank0":         int((zone_obj["rank"] == 0).sum()),
        "conflict_total":     conf_total,
        "conflict_overlap":   conf_overlap,
        "conflict_transport": conf_transport,
        "conflict_both":      conf_both,
        "dominant_type":      dominant,
    })

summary_df = pd.DataFrame(summary_rows)

# ─────────────────────────────────────────
# ДЕТАЛЬНАЯ ТАБЛИЦА: ЯЧЕЙКИ ПО ТИПАМ АКТИВНОСТИ
# ─────────────────────────────────────────

activity_rows = []
oopz_grid = grid_zoned[grid_zoned["mask_oopz"] == 1].copy()

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

# ─────────────────────────────────────────
# ТАБЛИЦА ОБЪЕКТОВ ПО ЗОНАМ, ТИПАМ И РАНГАМ
# ─────────────────────────────────────────

object_rows = []

for zone in zone_groups:
    zone_obj = oopz_zoned[oopz_zoned["zone_group"] == zone]
    if len(zone_obj) == 0:
        continue

    by_activity = zone_obj.groupby("activity_type").size().reset_index(name="total")
    for _, row in by_activity.iterrows():
        act = row["activity_type"] if pd.notna(row["activity_type"]) else "не определён"
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

# ─────────────────────────────────────────
# СОХРАНЕНИЕ
# ─────────────────────────────────────────

OUTPUT.parent.mkdir(parents=True, exist_ok=True)
summary_df.to_csv(OUTPUT, index=False, encoding="utf-8-sig")
activity_df.to_csv(OUTPUT_ACTIVITY, index=False, encoding="utf-8-sig")
objects_df.to_csv(OUTPUT_OBJECTS, index=False, encoding="utf-8-sig")

# ─────────────────────────────────────────
# ВЫВОД В КОНСОЛЬ
# ─────────────────────────────────────────

W = 82

print(f"\n{'─'*W}")
print(f"{'СВОДНАЯ СТАТИСТИКА ПО ЗОНАМ':^{W}}")
print(f"{'─'*W}")
print(f"{'Зона':<22} {'Ячеек':>7} {'Mask_S0':>9} {'%':>6} {'Всего':>7} {'rank1':>7} {'rank0':>7} {'Конфл.':>8}")
print(f"{'─'*W}")

for _, row in summary_df.iterrows():
    print(
        f"{row['zone_group']:<22} "
        f"{row['total_cells']:>7} "
        f"{row['mask_s0_cells']:>9} "
        f"{row['mask_s0_pct']:>5.1f}% "
        f"{row['oopz_objects_total']:>7} "
        f"{row['oopz_rank1']:>7} "
        f"{row['oopz_rank0']:>7} "
        f"{row['conflict_total']:>8}"
    )

print(f"\n{'─'*W}")
print(f"{'ОБЪЕКТЫ OOPZ ПО ЗОНАМ И ТИПАМ АКТИВНОСТИ':^{W}}")
print(f"{'─'*W}")
print(f"{'Зона':<22} {'Тип активности':<26} {'Всего':>6} {'rank1':>7} {'rank0':>7} {'polygon':>9} {'point':>7}")
print(f"{'─'*W}")

prev_zone = None
for zone in zone_groups:
    zone_data = objects_df[objects_df["zone_group"] == zone].sort_values("total", ascending=False)
    if len(zone_data) == 0:
        continue
    for _, row in zone_data.iterrows():
        zone_label = zone if zone != prev_zone else ""
        print(
            f"{zone_label:<22} "
            f"{row['activity_type']:<26} "
            f"{row['total']:>6} "
            f"{row['rank_1']:>7} "
            f"{row['rank_0']:>7} "
            f"{row['polygon']:>9} "
            f"{row['point']:>7}"
        )
        prev_zone = zone

print(f"\n{'─'*W}")
print(f"{'КОНФЛИКТЫ ПО ЗОНАМ':^{W}}")
print(f"{'─'*W}")
print(f"{'Зона':<22} {'Всего':>7} {'overlap':>10} {'transport':>12} {'both':>7}")
print(f"{'─'*W}")

for _, row in summary_df.iterrows():
    if row["conflict_total"] > 0:
        print(
            f"{row['zone_group']:<22} "
            f"{row['conflict_total']:>7} "
            f"{row['conflict_overlap']:>10} "
            f"{row['conflict_transport']:>12} "
            f"{row['conflict_both']:>7}"
        )

print(f"\nСохранено:")
print(f"  {OUTPUT}")
print(f"  {OUTPUT_ACTIVITY}")
print(f"  {OUTPUT_OBJECTS}")