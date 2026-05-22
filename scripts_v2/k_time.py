"""
k_time.py
Расчёт коэффициента K_time для модели NeedIndex.

Запуск:
    python scripts/k_time.py --city norilsk
    python scripts/k_time.py --city polyarnye_zori

Выход: output/k_time_table.csv  (season | slot | time_scenario | K_time)
Все параметры берутся из config.yaml города.
"""

import csv
import os
from datetime import date, datetime, timedelta
from astral import LocationInfo
from astral.sun import elevation
from utils import load_config, get_output_dir

# ── Конфиг ───────────────────────────────────────────────────────

config, BASE = load_config()

LOC  = config["location"]
STEP = config["step_minutes"]

# Даты сезонов — парсим из строк ISO формата ("2025-01-15")
SEASONS = {
    name: [date.fromisoformat(d) for d in dates]
    for name, dates in config["seasons"].items()
}

# Временные слоты — парсим из строк ("06:00", "12:00")
def _parse_time(s: str):
    h, m = map(int, s.split(":"))
    return h * 60 + m   # минуты от полуночи

SLOTS = {
    name: (_parse_time(start), _parse_time(end))
    for name, (start, end) in config["slots"].items()
}

PHASE_WEIGHTS = config["phase_weights"]

OUTPUT_CSV = get_output_dir(config, BASE) / "k_time_table.csv"

# ── Функции ───────────────────────────────────────────────────────

def get_phase(elev: float) -> str:
    """Определяет фазу освещённости по высоте солнца (градусы)."""
    if elev > 0:       return "day"
    elif elev > -6:    return "civil"
    elif elev > -12:   return "nautical"
    elif elev > -18:   return "astronomical"
    else:              return "night"


def build_slot_minutes(slot_name: str, slots: dict, step: int) -> list[int]:
    """
    Возвращает список минут от полуночи для временного слота.
    Слот 'night' (22:00–06:00) обрабатывается через полночь.

    Args:
        slot_name: имя слота из конфига
        slots:     словарь {slot_name: (start_minutes, end_minutes)}
        step:      шаг дискретизации в минутах
    """
    s, e = slots[slot_name]
    minutes = []

    if slot_name == "night":
        t = s
        while t < 24 * 60:
            minutes.append(t)
            t += step
        t = 0
        while t < e:
            minutes.append(t)
            t += step
    else:
        t = s
        while t < e:
            minutes.append(t)
            t += step

    return minutes


def calc_phase_shares(
    loc: LocationInfo,
    target_date: date,
    slot_name: str,
    slots: dict,
    step: int,
) -> dict:
    """
    Рассчитывает долю времени в каждой фазе освещённости для слота и даты.
    Для ночного слота минуты до 06:00 относятся к следующим суткам.
    """
    minutes = build_slot_minutes(slot_name, slots, step)
    phase_counts = {"day": 0, "civil": 0, "nautical": 0, "astronomical": 0, "night": 0}

    _, end = slots[slot_name]

    for m in minutes:
        hour, minute = m // 60, m % 60
        calc_date = (
            target_date + timedelta(days=1)
            if slot_name == "night" and m < end
            else target_date
        )
        dt   = datetime(calc_date.year, calc_date.month, calc_date.day, hour, minute)
        elev = elevation(loc.observer, dt, with_refraction=False)
        phase_counts[get_phase(elev)] += 1

    total = sum(phase_counts.values())
    return {p: phase_counts[p] / total for p in phase_counts}


def calc_k_time(phase_shares: dict, weights: dict) -> float:
    """Взвешенная сумма долей фаз освещённости."""
    return sum(weights[p] * phase_shares[p] for p in phase_shares)


def average_dicts(dicts: list[dict]) -> dict:
    """Усредняет список словарей с одинаковыми ключами."""
    keys = dicts[0].keys()
    return {k: sum(d[k] for d in dicts) / len(dicts) for k in keys}


# ── Main ──────────────────────────────────────────────────────────

def main():
    loc = LocationInfo(
        name=LOC["name"],
        region=LOC["region"],
        timezone=LOC["timezone"],
        latitude=LOC["latitude"],
        longitude=LOC["longitude"],
    )

    rows = []

    for season_name, dates in SEASONS.items():
        for slot_name in SLOTS:
            shares_list = [
                calc_phase_shares(loc, d, slot_name, SLOTS, STEP)
                for d in dates
            ]
            # Для межсезонья — среднее по двум датам
            shares = average_dicts(shares_list) if len(shares_list) > 1 else shares_list[0]

            for scenario_name, weights in PHASE_WEIGHTS.items():
                k = calc_k_time(shares, weights)
                rows.append({
                    "season":        season_name,
                    "slot":          slot_name,
                    "time_scenario": scenario_name,
                    "K_time":        round(k, 4),
                })
                print(f"{season_name:10} | {slot_name:8} | {scenario_name:12} | K_time = {k:.4f}")

    os.makedirs(OUTPUT_CSV.parent, exist_ok=True)
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["season", "slot", "time_scenario", "K_time"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nГотово. Таблица сохранена: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()