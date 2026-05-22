"""
run_all.py
Оркестратор — запускает все этапы модели NeedIndex последовательно.

Запуск:
    python scripts/run_all.py --city norilsk
    python scripts/run_all.py --city polyarnye_zori
    python scripts/run_all.py --city polyarnye_zori --skip grid mask
"""

import argparse
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent

# Порядок и имена этапов
PIPELINE = [
    ("grid",       "generate_grid.py",   "Генерация сетки"),
    ("k_time",     "k_time.py",          "Расчёт K_time"),
    ("mask",       "mask_s0.py",         "Формирование маски S0"),
    ("index",      "need_index.py",      "Расчёт NeedIndex (базовый)"),
    ("scenarios",  "scenarios_export.py","Экспорт сценариев в xlsx"),
    ("gen_blocks", "generate_blocks.py", "Генерация кварталов"),
    ("blocks",     "blocks.py",          "Агрегация по кварталам"),
    ("stats",      "zone_stats.py",      "Статистика по зонам"),
    ("passport",   "passport_s0.py",     "Паспорт световой среды"),
]

parser = argparse.ArgumentParser()
parser.add_argument("--city",  required=True,  help="Название города")
parser.add_argument("--skip",  nargs="*", default=[], help="Этапы для пропуска")
parser.add_argument("--only",  nargs="*", default=[], help="Запустить только эти этапы")
args = parser.parse_args()

print(f"\n{'═'*50}")
print(f"  NeedIndex pipeline → {args.city}")
print(f"{'═'*50}\n")

errors = []
for key, script, label in PIPELINE:
    if args.only and key not in args.only:
        continue
    if key in args.skip:
        print(f"  [ПРОПУСК] {label}")
        continue

    print(f"\n{'─'*50}")
    print(f"  [{key.upper()}] {label}")
    print(f"{'─'*50}")

    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / script), "--city", args.city],
        capture_output=False,
    )

    if result.returncode != 0:
        print(f"\n  ✗ Ошибка на этапе [{key}]. Остановка.")
        errors.append(key)
        break

print(f"\n{'═'*50}")
if errors:
    print(f"  Завершено с ошибками: {errors}")
else:
    print(f"  ✓ Все этапы выполнены успешно → {args.city}")
print(f"{'═'*50}\n")