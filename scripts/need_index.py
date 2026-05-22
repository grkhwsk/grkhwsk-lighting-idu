"""
need_index.py
Расчёт индекса потребности в искусственном освещении NeedIndex
для одного заданного сценария.

Формула:
    NeedIndex(x, slot, season, albedo) =
        Mask_S0(x) × Active(x, slot) × K_time(slot, season, scenario) × K_albedo(albedo)

Выходной файл:
    data/scenarios/NI_{season}_{slot}_{albedo}_{scenario}.gpkg
"""

import geopandas as gpd
import pandas as pd
import yaml
from pathlib import Path

# ─────────────────────────────────────────
# ПАРАМЕТРЫ СЦЕНАРИЯ — задайте здесь
# ─────────────────────────────────────────

SEASON = "midseason"  # winter | midseason | summer
SLOT = "evening"  # morning | day | evening | night
ALBEDO = "no_snow"  # no_snow | dirty_snow | clean_snow
SCENARIO = "scenario_3"  # scenario_1 | scenario_2 | scenario_3

# ─────────────────────────────────────────

print(f"\n── Параметры расчёта ───────────────────")
print(f"  Сезон:      {SEASON}")
print(f"  Слот:       {SLOT}")
print(f"  Альбедо:    {ALBEDO}")
print(f"  Сценарий:   {SCENARIO}")

# ─────────────────────────────────────────
# ПУТИ К ФАЙЛАМ
# ─────────────────────────────────────────

BASE = Path(__file__).parent.parent

GRID_S0 = BASE / "data/interim/grid_s0_1.gpkg"
K_TIME = BASE / "output/k_time_table.csv"
CONFIG = BASE / "config.yaml"

OUTPUT_NAME = f"NI_{SEASON}_{SLOT}_{ALBEDO}_{SCENARIO}.gpkg"
OUTPUT = BASE / "data/scenarios" / OUTPUT_NAME

# ─────────────────────────────────────────
# ВАЛИДАЦИЯ ПАРАМЕТРОВ
# ─────────────────────────────────────────
# Летом снег невозможен — допустимо только no_snow

VALID_ALBEDO = {
    "summer": ["no_snow"],
    "winter": ["no_snow", "dirty_snow", "clean_snow"],
    "midseason": ["no_snow", "dirty_snow", "clean_snow"],
}

if ALBEDO not in VALID_ALBEDO[SEASON]:
    raise ValueError(
        f"Недопустимая комбинация: season='{SEASON}', albedo='{ALBEDO}'.\n"
        f"Для сезона '{SEASON}' допустимы: {VALID_ALBEDO[SEASON]}"
    )

print("Валидация параметров пройдена.")

# ─────────────────────────────────────────
# ЗАГРУЗКА КОНФИГУРАЦИИ
# ─────────────────────────────────────────

print("\nЗагрузка конфигурации...")

with open(CONFIG, "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

k_albedo = config["albedo"]["scenarios"][ALBEDO]["K_albedo"]
print(f"  K_albedo ({ALBEDO}): {k_albedo}")

TAU1 = config["thresholds"]["tau_1"]
TAU2 = config["thresholds"]["tau_2"]
print(f"  Пороги: τ₁ = {TAU1}, τ₂ = {TAU2}")

# ─────────────────────────────────────────
# ЗАГРУЗКА ВХОДНЫХ ДАННЫХ
# ─────────────────────────────────────────

print("Загрузка данных...")

grid = gpd.read_file(GRID_S0)
print(f"  Ячеек в сетке:   {len(grid)}")
print(f"  Mask_S0 = 1:     {grid['Mask_S0'].sum()}")

k_time_df = pd.read_csv(K_TIME)

# ─────────────────────────────────────────
# ИЗВЛЕЧЕНИЕ K_TIME
# ─────────────────────────────────────────

k_time_row = k_time_df[
    (k_time_df["season"] == SEASON)
    & (k_time_df["slot"] == SLOT)
    & (k_time_df["time_scenario"] == SCENARIO)
]

if len(k_time_row) == 0:
    raise ValueError(f"K_time не найден для: {SEASON} / {SLOT} / {SCENARIO}")

k_time = float(k_time_row["K_time"].values[0])
print(f"  K_time: {k_time}")

# ─────────────────────────────────────────
# РАСЧЁТ NEEDINDEX
# ─────────────────────────────────────────

active_col = f"active_{SLOT}"

print(f"\nРасчёт NeedIndex...")
print(f"  Активных ячеек в слоте '{SLOT}': {(grid[active_col] == 1).sum()}")

result = grid.copy()

result["NeedIndex"] = (
    result["Mask_S0"] * result[active_col] * k_time * k_albedo
).round(4)

# ─────────────────────────────────────────
# КЛАССИФИКАЦИЯ ПО ПОРОГАМ
# ─────────────────────────────────────────


def classify(val):
    if val == 0:
        return 0
    elif val <= TAU1:
        return 1
    elif val <= TAU2:
        return 2
    else:
        return 3


result["need_class"] = result["NeedIndex"].apply(classify)

# ─────────────────────────────────────────
# СОХРАНЕНИЕ
# ─────────────────────────────────────────

keep_cols = [
    "id",
    "Mask_S0",
    "mask_24h",
    "source",
    "dominant_type",
    "activity_types",
    "conflict_type",
    "NeedIndex",
    "need_class",
    "geometry",
]
keep_cols = [c for c in keep_cols if c in result.columns]

OUTPUT.parent.mkdir(parents=True, exist_ok=True)
result[keep_cols].to_file(OUTPUT, driver="GPKG")

# ─────────────────────────────────────────
# СТАТИСТИКА
# ─────────────────────────────────────────

ni = result["NeedIndex"]
nc = result["need_class"]

print(f"\n── Результат ───────────────────────────")
print(f"  Файл:                  {OUTPUT_NAME}")
print(f"  Всего ячеек:           {len(result)}")
print(
    f"  NeedIndex > 0:         {(ni > 0).sum()} ({(ni > 0).sum()/len(result)*100:.1f}%)"
)
print(f"  Среднее (все):         {ni.mean():.4f}")
if (ni > 0).any():
    print(f"  Среднее (активные):    {ni[ni > 0].mean():.4f}")
print(f"  Максимум:              {ni.max():.4f}")
print(f"\n── Классификация ───────────────────────")
print(f"  Класс 0 (нет):         {(nc == 0).sum()}")
print(f"  Класс 1 (низкая):      {(nc == 1).sum()}")
print(f"  Класс 2 (средняя):     {(nc == 2).sum()}")
print(f"  Класс 3 (высокая):     {(nc == 3).sum()}")
print(f"\nСохранено: {OUTPUT}")
