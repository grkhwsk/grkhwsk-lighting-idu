"""
need_index.py
Расчёт индекса потребности в искусственном освещении NeedIndex.

Формула:
    NeedIndex(x) = Mask_S0(x) × Active(x, slot) × K_time(slot, season, scenario) × K_albedo(albedo)

Запуск с параметрами базового сценария из config.yaml:
    python scripts/need_index.py --city norilsk
    python scripts/need_index.py --city polyarnye_zori

Запуск с явным указанием сценария:
    python scripts/need_index.py --city norilsk --season winter --slot night --albedo no_snow --scenario scenario_2

Выход:
    data/scenarios/NI_{season}_{slot}_{albedo}_{scenario}.gpkg
"""

import argparse
import geopandas as gpd
import numpy as np
import pandas as pd
from utils import load_config, get_output_dir

# ── Конфиг и аргументы ───────────────────────────────────────────
# load_config() читает --city; здесь добавляем параметры сценария
# с дефолтами из baseline конфига

config, BASE = load_config()
baseline = config["baseline"]

# Дополнительные аргументы сценария (не конфликтуют с --city)
_parser = argparse.ArgumentParser(add_help=False)
_parser.add_argument("--season",   default=baseline["season"])
_parser.add_argument("--slot",     default=baseline["slot"])
_parser.add_argument("--albedo",   default=baseline["albedo"])
_parser.add_argument("--scenario", default=baseline["time_scenario"])
_args, _ = _parser.parse_known_args()

SEASON   = _args.season
SLOT     = _args.slot
ALBEDO   = _args.albedo
SCENARIO = _args.scenario

print(f"\n── Параметры расчёта ───────────────────")
print(f"  Город:      {config['location']['name']}")
print(f"  Сезон:      {SEASON}")
print(f"  Слот:       {SLOT}")
print(f"  Альбедо:    {ALBEDO}")
print(f"  Сценарий:   {SCENARIO}")

# ── Валидация параметров ──────────────────────────────────────────
# Летом снег невозможен физически

VALID_ALBEDO = {
    "summer":    ["no_snow"],
    "winter":    ["no_snow", "dirty_snow", "clean_snow"],
    "midseason": ["no_snow", "dirty_snow", "clean_snow"],
}

if SEASON not in VALID_ALBEDO:
    raise ValueError(f"Неизвестный сезон: '{SEASON}'. Допустимы: {list(VALID_ALBEDO)}")

if ALBEDO not in VALID_ALBEDO[SEASON]:
    raise ValueError(
        f"Недопустимая комбинация: season='{SEASON}', albedo='{ALBEDO}'.\n"
        f"Для сезона '{SEASON}' допустимы: {VALID_ALBEDO[SEASON]}"
    )

if SLOT not in config["slots"]:
    raise ValueError(f"Неизвестный слот: '{SLOT}'. Допустимы: {list(config['slots'])}")

if SCENARIO not in config["phase_weights"]:
    raise ValueError(f"Неизвестный сценарий: '{SCENARIO}'. Допустимы: {list(config['phase_weights'])}")

print("  Валидация пройдена.")

# ── Пути ─────────────────────────────────────────────────────────

INTERIM_DIR   = BASE / config["paths"]["data_generated"]
SCENARIOS_DIR = BASE / config["paths"]["data_scenarios"]

GRID_S0 = BASE / config["paths"]["data_generated"] / "grid_s0.gpkg"
K_TIME_CSV  = get_output_dir(config, BASE) / "k_time_table.csv"
OUTPUT_NAME = f"NI_{SEASON}_{SLOT}_{ALBEDO}_{SCENARIO}.gpkg"
OUTPUT      = SCENARIOS_DIR / OUTPUT_NAME

# ── Загрузка конфига ─────────────────────────────────────────────

k_albedo = config["albedo"]["scenarios"][ALBEDO]["K_albedo"]
TAU1     = config["thresholds"]["tau_1"]
TAU2     = config["thresholds"]["tau_2"]

print(f"\n  K_albedo ({ALBEDO}): {k_albedo}")
print(f"  Пороги: τ₁ = {TAU1}, τ₂ = {TAU2}")

# ── Загрузка данных ───────────────────────────────────────────────

print("\nЗагрузка данных...")

if not GRID_S0.exists():
    raise FileNotFoundError(
        f"Сетка не найдена: {GRID_S0}\n"
        f"Сначала запустите mask_s0.py --city {BASE.name}"
    )

if not K_TIME_CSV.exists():
    raise FileNotFoundError(
        f"Таблица K_time не найдена: {K_TIME_CSV}\n"
        f"Сначала запустите k_time.py --city {BASE.name}"
    )

grid      = gpd.read_file(GRID_S0)
k_time_df = pd.read_csv(K_TIME_CSV)

print(f"  Ячеек в сетке: {len(grid)}")
print(f"  Mask_S0 = 1:   {grid['Mask_S0'].sum()}")

# ── Извлечение K_time ─────────────────────────────────────────────

k_time_row = k_time_df[
    (k_time_df["season"]        == SEASON)   &
    (k_time_df["slot"]          == SLOT)     &
    (k_time_df["time_scenario"] == SCENARIO)
]

if len(k_time_row) == 0:
    raise ValueError(
        f"K_time не найден для: season='{SEASON}', slot='{SLOT}', scenario='{SCENARIO}'.\n"
        f"Проверьте k_time_table.csv или пересчитайте k_time.py."
    )

k_time = float(k_time_row["K_time"].values[0])
print(f"  K_time: {k_time}")

# ── Расчёт NeedIndex ─────────────────────────────────────────────

active_col = f"active_{SLOT}"

if active_col not in grid.columns:
    raise KeyError(
        f"Колонка '{active_col}' не найдена в сетке.\n"
        f"Проверьте что mask_s0.py был запущен с тем же набором слотов."
    )

print(f"\nРасчёт NeedIndex...")
print(f"  Активных ячеек в слоте '{SLOT}': {(grid[active_col] == 1).sum()}")

result = grid.copy()
result["NeedIndex"] = (
    result["Mask_S0"] * result[active_col] * k_time * k_albedo
).round(4)

# Классификация — векторизовано через np.select вместо apply()
ni = result["NeedIndex"]
result["need_class"] = np.select(
    [ni == 0, ni <= TAU1, ni <= TAU2],
    [0, 1, 2],
    default=3,
)

# ── Сохранение ────────────────────────────────────────────────────

keep_cols = [c for c in [
    "id", "Mask_S0", "mask_24h", "source", "dominant_type",
    "activity_types", "conflict_type", "NeedIndex", "need_class", "geometry",
] if c in result.columns]

SCENARIOS_DIR.mkdir(parents=True, exist_ok=True)
result[keep_cols].to_file(OUTPUT, driver="GPKG")

# ── Статистика ────────────────────────────────────────────────────

ni = result["NeedIndex"]
nc = result["need_class"]

print(f"\n── Результат ───────────────────────────")
print(f"  Файл:              {OUTPUT_NAME}")
print(f"  Всего ячеек:       {len(result)}")
print(f"  NeedIndex > 0:     {(ni > 0).sum()} ({(ni > 0).sum() / len(result) * 100:.1f}%)")
print(f"  Среднее (все):     {ni.mean():.4f}")
if (ni > 0).any():
    print(f"  Среднее (активные): {ni[ni > 0].mean():.4f}")
print(f"  Максимум:          {ni.max():.4f}")
print(f"\n── Классификация ───────────────────────")
print(f"  Класс 0 (нет):     {(nc == 0).sum()}")
print(f"  Класс 1 (низкая):  {(nc == 1).sum()}")
print(f"  Класс 2 (средняя): {(nc == 2).sum()}")
print(f"  Класс 3 (высокая): {(nc == 3).sum()}")
print(f"\nСохранено: {OUTPUT}")