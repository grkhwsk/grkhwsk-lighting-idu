"""
utils.py
Общие утилиты для скриптов модели NeedIndex.

Использование в любом скрипте:
    from utils import load_config, get_path, get_output_dir, get_shared_path

    config, BASE = load_config()
    grid_path    = get_path(config, BASE, "grid")
    matrix_path  = get_shared_path(config, BASE, "activity_matrix")
"""

import argparse
import yaml
from pathlib import Path


def load_config() -> tuple[dict, Path]:
    """
    Разбирает аргумент --city, загружает config.yaml из папки города.

    Возвращает:
        config — словарь из config.yaml
        BASE   — Path до папки города (cities/{city}/)
    """
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--city",
        required=True,
        help="Название города — папка в cities/. Пример: --city norilsk",
    )
    args, _ = parser.parse_known_args()

    repo_root = Path(__file__).parent.parent
    BASE = repo_root / "cities" / args.city

    if not BASE.exists():
        raise FileNotFoundError(
            f"Папка города не найдена: {BASE}\n"
            f"Создайте папку cities/{args.city}/ и положите в неё config.yaml"
        )

    config_path = BASE / "config.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"config.yaml не найден: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    print(f"── Город: {config['location']['name']} {'──' * 15}")
    return config, BASE


def get_path(config: dict, BASE: Path, layer_key: str) -> Path:
    """
    Возвращает абсолютный путь к слою по ключу из config.yaml → layers.

    Пример:
        get_path(config, BASE, "grid")
        → cities/norilsk/data/generated/grid_25_aoi.gpkg
    """
    layers = config.get("layers", {})
    if layer_key not in layers:
        raise KeyError(
            f"Ключ '{layer_key}' не найден в блоке layers config.yaml.\n"
            f"Доступные ключи: {list(layers.keys())}"
        )
    return BASE / layers[layer_key]


def get_shared_path(config: dict, BASE: Path, key: str) -> Path:
    """
    Возвращает путь к общему ресурсу модели, единому для всех городов.
    Путь разрешается относительно корня репозитория (не папки города).

    BASE.parent.parent вычисляет repo_root из cities/{city}/ автоматически —
    сигнатура load_config() при этом не меняется.

    Пример:
        get_shared_path(config, BASE, "activity_matrix")
        → project_root/model/activity_matrix.csv
    """
    shared = config.get("shared", {})
    if key not in shared:
        raise KeyError(
            f"Ключ '{key}' не найден в блоке shared config.yaml.\n"
            f"Доступные ключи: {list(shared.keys())}"
        )
    repo_root = BASE.parent.parent  # cities/{city} → cities → repo_root
    return repo_root / shared[key]


def get_output_dir(config: dict, BASE: Path, subdir: str = "") -> Path:
    """
    Возвращает путь к папке вывода, создаёт её при необходимости.

    Пример:
        get_output_dir(config, BASE)         → cities/norilsk/output/
        get_output_dir(config, BASE, "maps") → cities/norilsk/output/maps/
    """
    out = BASE / config["paths"]["output"]
    if subdir:
        out = out / subdir
    out.mkdir(parents=True, exist_ok=True)
    return out