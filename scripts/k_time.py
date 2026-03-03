"""
k_time.py
Расчёт коэффициента K_time для модели NeedIndex.

Выход: CSV-таблица (season | slot | time_scenario | K_time)
Все параметры задаются в блоке CONFIG.
"""

import csv
from datetime import date, time, datetime, timedelta
from astral import LocationInfo
from astral.sun import sun, elevation

# ─────────────────────────────────────────
# CONFIG — все параметры модели
# ─────────────────────────────────────────

LOCATION = {
    "name":      "Norilsk",
    "region":    "Russia",
    "timezone":  "Asia/Krasnoyarsk",   # UTC+7
    "latitude":  69.3535,
    "longitude": 88.2027,
}

# Даты сезонов
SEASONS = {
    "winter":   [date(2025, 1, 15)],
    "summer":   [date(2025, 7, 15)],
    "midseason": [date(2025, 4, 15), date(2025, 10, 15)],  # среднее
}

# Временные слоты (локальное время)
SLOTS = {
    "morning": (time(6, 0),  time(12, 0)),
    "day":     (time(12, 0), time(18, 0)),
    "evening": (time(18, 0), time(22, 0)),
    "night":   (time(22, 0), time(6, 0)),   # переход через полночь
}

# Веса фаз освещённости по сценариям
# Фазы: day | civil | nautical | astronomical | night
PHASE_WEIGHTS = {
    "scenario_1": {"day": 0.0, "civil": 0.3, "nautical": 0.7, "astronomical": 0.9, "night": 1.0},
    "scenario_2": {"day": 0.0, "civil": 0.5, "nautical": 0.9, "astronomical": 1.0, "night": 1.0},
    "scenario_3": {"day": 0.0, "civil": 0.2, "nautical": 0.5, "astronomical": 0.8, "night": 1.0},
}

# Шаг дискретизации (минуты)
STEP_MINUTES = 10

# Выходной файл
OUTPUT_CSV = "output/k_time_table.csv"

# ─────────────────────────────────────────
# ФУНКЦИИ
# ─────────────────────────────────────────

def get_phase(elev: float) -> str:
    """Определяет фазу освещённости по высоте солнца (градусы)."""
    if elev > 0:
        return "day"
    elif elev > -6:
        return "civil"
    elif elev > -12:
        return "nautical"
    elif elev > -18:
        return "astronomical"
    else:
        return "night"


def build_slot_minutes(slot_name: str):
    """
    Возвращает список минут от полуночи для слота.
    Слот 'night' (22:00–06:00) разбивается через полночь.
    """
    start, end = SLOTS[slot_name]
    s = start.hour * 60 + start.minute
    e = end.hour * 60 + end.minute

    minutes = []
    if slot_name == "night":
        # 22:00 → 23:59
        t = s
        while t < 24 * 60:
            minutes.append(t)
            t += STEP_MINUTES
        # 00:00 → 06:00
        t = 0
        while t < e:
            minutes.append(t)
            t += STEP_MINUTES
    else:
        t = s
        while t < e:
            minutes.append(t)
            t += STEP_MINUTES
    return minutes


def calc_phase_shares(loc: LocationInfo, target_date: date, slot_name: str) -> dict:
    """
    Рассчитывает долю времени в каждой фазе освещённости для слота и даты.
    """
    minutes = build_slot_minutes(slot_name)
    phase_counts = {"day": 0, "civil": 0, "nautical": 0, "astronomical": 0, "night": 0}

    for m in minutes:
        hour = m // 60
        minute = m % 60
        # Для ночного слота минуты после 22:00 относятся к target_date,
        # минуты до 06:00 — к следующему дню
        if slot_name == "night" and m < 6 * 60:
            calc_date = target_date + timedelta(days=1)
        else:
            calc_date = target_date

        dt = datetime(calc_date.year, calc_date.month, calc_date.day, hour, minute)
        elev = elevation(loc.observer, dt, with_refraction=False)
        phase = get_phase(elev)
        phase_counts[phase] += 1

    total = sum(phase_counts.values())
    return {p: phase_counts[p] / total for p in phase_counts}


def calc_k_time(phase_shares: dict, weights: dict) -> float:
    """Взвешенная сумма долей фаз."""
    return sum(weights[p] * phase_shares[p] for p in phase_shares)


def average_dicts(dicts: list) -> dict:
    """Усредняет список словарей с одинаковыми ключами."""
    keys = dicts[0].keys()
    return {k: sum(d[k] for d in dicts) / len(dicts) for k in keys}


# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────

def main():
    loc = LocationInfo(
        name=LOCATION["name"],
        region=LOCATION["region"],
        timezone=LOCATION["timezone"],
        latitude=LOCATION["latitude"],
        longitude=LOCATION["longitude"],
    )

    rows = []

    for season_name, dates in SEASONS.items():
        for slot_name in SLOTS:
            # Рассчитываем доли фаз для каждой даты сезона
            shares_list = [calc_phase_shares(loc, d, slot_name) for d in dates]
            # Для shoulder — среднее по двум датам
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

    # Запись CSV
    import os
    os.makedirs("output", exist_ok=True)
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["season", "slot", "time_scenario", "K_time"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nГотово. Таблица сохранена: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()