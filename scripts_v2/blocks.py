"""
blocks.py
Агрегация результатов NeedIndex и POI по кварталам.

Запуск:
    python scripts/blocks.py --city norilsk
    python scripts/blocks.py --city polyarnye_zori

Выход:
    data/interim/blocks_final.gpkg
"""

import geopandas as gpd
import pandas as pd
from utils import load_config, get_path

# ── Конфиг ───────────────────────────────────────────────────────

config, BASE = load_config()

CRS           = config["location"]["crs"]
INTERIM_DIR   = BASE / config["paths"]["data_interim"]
SCENARIOS_DIR = BASE / config["paths"]["data_scenarios"]
BASELINE      = config["baseline"]

BLOCKS_IN = get_path(config, BASE, "blocks_raw")
ZONES     = get_path(config, BASE, "zones")
GRID_S0 = BASE / config["paths"]["data_generated"] / "grid_s0.gpkg"
OUTPUT    = get_path(config, BASE, "blocks")

# ── Загрузка кварталов и зон ─────────────────────────────────────

print("\nЗагрузка данных...")
blocks = gpd.read_file(BLOCKS_IN)
zones  = gpd.read_file(ZONES).to_crs(CRS)
print(f"  Кварталов: {len(blocks)}")
print(f"  Зон:       {len(zones)}")

# ── Зона по центроиду квартала ────────────────────────────────────

centroids = blocks.copy()
centroids["geometry"] = centroids.geometry.centroid

joined = gpd.sjoin(
    centroids[["block_id", "area_m2", "geometry"]],
    zones[["zone_group", "zone_code", "geometry"]],
    how="left",
    predicate="within",
)
joined["zone_group"] = joined["zone_group"].fillna("Outside")
result = joined[["block_id", "area_m2", "zone_group", "zone_code"]].copy()

# ── Автообнаружение сценариев ─────────────────────────────────────
# Читаем все NI_*.gpkg из папки — список не нужно обновлять вручную

if not SCENARIOS_DIR.exists():
    raise FileNotFoundError(
        f"Папка сценариев не найдена: {SCENARIOS_DIR}\n"
        f"Сначала запустите need_index.py"
    )

scenarios = {p.stem: p for p in sorted(SCENARIOS_DIR.glob("NI_*.gpkg"))}

if not scenarios:
    raise FileNotFoundError(f"Нет файлов NI_*.gpkg в {SCENARIOS_DIR}")

print(f"  Сценариев найдено: {len(scenarios)}")

# ── NeedIndex по сценариям ────────────────────────────────────────

for label, path in scenarios.items():
    ni = gpd.read_file(path)
    ni_in = gpd.sjoin(
        ni[["NeedIndex", "geometry"]],
        blocks[["block_id", "geometry"]],
        how="left",
        predicate="within",
    )
    stats = ni_in.groupby("block_id").agg(
        ni_mean=("NeedIndex", "mean"),
        active_pct=("NeedIndex", lambda x: round((x > 0).sum() / len(x) * 100, 1)),
    ).reset_index()
    stats.columns = ["block_id", f"ni_{label}", f"pct_{label}"]
    result = result.merge(stats, on="block_id", how="left")

# ── Покрытие маской S0 ────────────────────────────────────────────

print("Расчёт покрытия маской...")
grid_s0 = gpd.read_file(GRID_S0)

mask_in = gpd.sjoin(
    grid_s0[["Mask_S0", "geometry"]],
    blocks[["block_id", "geometry"]],
    how="left",
    predicate="within",
)
mask_stats = mask_in.groupby("block_id").agg(
    mask_pct=("Mask_S0", lambda x: round(x.sum() / len(x) * 100, 1))
).reset_index()
result = result.merge(mask_stats, on="block_id", how="left")
result["mask_pct"] = result["mask_pct"].fillna(0)

# ── Потребность 24h ───────────────────────────────────────────────

baseline_stem = (
    f"NI_{BASELINE['season']}_{BASELINE['slot']}_"
    f"{BASELINE['albedo']}_{BASELINE['time_scenario']}"
)
baseline_path = SCENARIOS_DIR / f"{baseline_stem}.gpkg"

if baseline_path.exists():
    ni_baseline = gpd.read_file(baseline_path)
    if "mask_24h" in ni_baseline.columns:
        ni_24h = gpd.sjoin(
            ni_baseline[["mask_24h", "geometry"]],
            blocks[["block_id", "geometry"]],
            how="left",
            predicate="within",
        )
        stats_24h = ni_24h.groupby("block_id").agg(
            pct_24h=("mask_24h", lambda x: round(x.sum() / len(x) * 100, 1))
        ).reset_index()
        result = result.merge(stats_24h, on="block_id", how="left")
        result["pct_24h"] = result["pct_24h"].fillna(0)

        top_cols = ["block_id", "zone_group", "pct_24h"]
        baseline_col = f"ni_{baseline_stem}"
        if baseline_col in result.columns:
            top_cols.append(baseline_col)
        print("\nТоп кварталов по pct_24h:")
        print(result.nlargest(5, "pct_24h")[top_cols].to_string())
else:
    print(f"  Внимание: базовый сценарий не найден — {baseline_path.name}")
    print("  pct_24h не рассчитан. Запустите need_index.py.")

# ── POI по кварталам ─────────────────────────────────────────────

print("\nАгрегация POI по кварталам...")

poi_layer_keys = ["poi_facility_poly", "poi_facility_terr", "poi_space", "poi_points"]
poi_parts = []

for key in poi_layer_keys:
    path = get_path(config, BASE, key)
    if not path.exists():
        print(f"  Внимание: слой не найден — {path.name}")
        continue
    gdf = gpd.read_file(path)
    if "activity_type" not in gdf.columns or "rank" not in gdf.columns:
        print(f"  Внимание: нет колонок activity_type/rank в {path.name} — пропущен")
        continue
    poi_parts.append(gdf[["activity_type", "rank", "geometry"]])

if not poi_parts:
    raise FileNotFoundError("Не найден ни один POI-слой. Проверьте config.yaml → layers.")

poi_all = gpd.GeoDataFrame(
    pd.concat(poi_parts, ignore_index=True),
    geometry="geometry",
    crs=poi_parts[0].crs,
).to_crs(CRS)

# Только rank 1, центроиды
poi_r1 = poi_all[poi_all["rank"] == 1].copy()
poi_r1["geometry"] = poi_r1.geometry.centroid

poi_in_blocks = gpd.sjoin(
    poi_r1[["activity_type", "geometry"]],
    blocks[["block_id", "geometry"]],
    how="left",
    predicate="within",
)

poi_count = poi_in_blocks.groupby("block_id").agg(
    poi_count=("activity_type", "count"),
    dominant_type=("activity_type", lambda x: x.value_counts().index[0]),
).reset_index()

poi_pivot = (
    poi_in_blocks.groupby(["block_id", "activity_type"])
    .size()
    .unstack(fill_value=0)
)
poi_pivot.columns = [f"poi_{c}" for c in poi_pivot.columns]
poi_pivot = poi_pivot.reset_index()

result = result.merge(poi_count, on="block_id", how="left")
result = result.merge(poi_pivot, on="block_id", how="left")
result["poi_count"]     = result["poi_count"].fillna(0).astype(int)
result["dominant_type"] = result["dominant_type"].fillna("—")

for col in result.columns:
    if col.startswith("ni_"):
        result[col] = result[col].round(3)

# ── Сохранение ────────────────────────────────────────────────────

result_gdf = gpd.GeoDataFrame(
    result,
    geometry=blocks.set_index("block_id").loc[result["block_id"].values, "geometry"].values,
    crs=CRS,
)
OUTPUT.parent.mkdir(parents=True, exist_ok=True)
result_gdf.to_file(OUTPUT, driver="GPKG")

# ── Сводная статистика ────────────────────────────────────────────

baseline_col = f"ni_{baseline_stem}"
winter_cols  = [c for c in result_gdf.columns if "winter" in c and c.startswith("ni_")]

agg_dict = {
    "кварталов":   ("block_id", "count"),
    "poi_avg":     ("poi_count", lambda x: round(x.mean(), 1)),
    "площадь_км2": ("area_m2", lambda x: round(x.sum() / 1e6, 2)),
}
if baseline_col in result_gdf.columns:
    agg_dict["ni_базовый"] = (baseline_col, lambda x: round(x.mean(), 3))
if winter_cols:
    agg_dict["ni_зима"] = (winter_cols[0], lambda x: round(x.mean(), 3))

print("\nПо зонам:")
print(result_gdf.groupby("zone_group").agg(**agg_dict).to_string())

top_cols = ["block_id", "zone_group", "poi_count", "dominant_type"]
if baseline_col in result_gdf.columns:
    top_cols.append(baseline_col)

print("\nТоп кварталов по POI rank 1:")
print(result_gdf.nlargest(10, "poi_count")[top_cols].to_string())

print(f"\nСохранено: {OUTPUT}")