#!/usr/bin/env python3
"""
Еженедельное обновление блока competitor_matrix в data.json.

Стратегия: manual-first + постепенная автоматизация.
Сейчас скрипт делает три вещи:

  1. Читает текущий data.json.
  2. Для каждого банка вызывает parser-функцию. Парсеры возвращают либо
     свежие числа (если селекторы живые), либо None (если сайт изменился).
  3. Если parser вернул None — оставляет предыдущее значение из data.json,
     помечает entry как stale (updated_at не меняется), логгирует в
     STDOUT/файл. Если parser вернул данные — заменяет entry.

Парсеры банковских страниц хрупкие: HTML меняется, есть антибот-защита.
Все функции _parse_* — SCAFFOLD-ы. Стабилизируются итеративно: сначала
данные заводятся руками через seed_competitor_matrix.json, парсеры
проверяются на реальных страницах и включаются по одному.

Запуск:
    python scripts/refresh_competitors.py \
        --data-json data.json \
        --registry sources/registry.yaml \
        --output data.json \
        --log-file /tmp/refresh.log
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable, Optional

import requests
import yaml
from bs4 import BeautifulSoup

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
REQUEST_TIMEOUT = 15
TODAY_ISO = dt.date.today().isoformat()

log = logging.getLogger("refresh_competitors")


# ---------------------------------------------------------------------------
# Схема одной записи competitor_matrix
# ---------------------------------------------------------------------------
@dataclass
class CompetitorEntry:
    bank: str                    # sber | vtb | gpb | psb | pochta | sovcom | tbank
    product_key: str             # consumer_loan | mil_mortgage | premium_service | ...
    product_name: str            # маркетинговое название продукта
    rate_min: Optional[float]    # годовая ставка %
    rate_max: Optional[float]
    max_amount_rub: Optional[int]
    term_months_max: Optional[int]
    usp: str                     # уникальное торговое предложение
    weakness: str                # слабое место
    source_url: str
    updated_at: str              # YYYY-MM-DD
    is_stale: bool = False       # True если парсер упал и данные старые


# ---------------------------------------------------------------------------
# HTTP-помощник
# ---------------------------------------------------------------------------
def fetch(url: str) -> Optional[str]:
    try:
        r = requests.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "ru,en;q=0.9"},
            timeout=REQUEST_TIMEOUT,
        )
        if r.status_code == 200:
            return r.text
        log.warning("fetch %s -> HTTP %s", url, r.status_code)
    except requests.RequestException as e:
        log.warning("fetch %s -> %s", url, e)
    return None


def extract_percent(text: str) -> Optional[float]:
    """Первое число в формате '21,5%' или '21.5 %'."""
    m = re.search(r"(\d+[.,]\d+|\d+)\s*%", text)
    if not m:
        return None
    return float(m.group(1).replace(",", "."))


def extract_amount_rub(text: str) -> Optional[int]:
    """Число + 'млн ₽' / 'тыс. ₽' / '000 ₽'."""
    m = re.search(r"(\d+[.,]?\d*)\s*(млн|тыс|000)\s*₽?", text, re.IGNORECASE)
    if not m:
        return None
    value = float(m.group(1).replace(",", "."))
    unit = m.group(2).lower()
    multiplier = {"млн": 1_000_000, "тыс": 1_000, "000": 1_000}[unit]
    return int(value * multiplier)


# ---------------------------------------------------------------------------
# Парсеры банков — SCAFFOLD-ы. Включать по мере верификации.
# ---------------------------------------------------------------------------
def _parse_sber_consumer_loan() -> Optional[CompetitorEntry]:
    """TODO: включить после сверки селекторов на sberbank.ru."""
    log.info("sber_consumer_loan: parser disabled (scaffold)")
    return None


def _parse_vtb_consumer_loan() -> Optional[CompetitorEntry]:
    """TODO: vtb.ru/personal/kredity — селектор ставки."""
    log.info("vtb_consumer_loan: parser disabled (scaffold)")
    return None


def _parse_psb_military() -> Optional[CompetitorEntry]:
    """psbank.ru/personal/loans/creditaction — «Для военных и гражданских
    пенсионеров». Ставка 26,9–36,9% с акцией «Лучше ноль»."""
    html = fetch("https://www.psbank.ru/personal/loans/creditaction")
    if not html:
        return None
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ", strip=True)
    rate_min = extract_percent(text)
    if rate_min is None:
        log.warning("psb_military: rate not found on page")
        return None
    return CompetitorEntry(
        bank="psb",
        product_key="consumer_loan",
        product_name="Для военных и гражданских пенсионеров",
        rate_min=rate_min,
        rate_max=None,
        max_amount_rub=3_000_000,
        term_months_max=84,
        usp="Акция «Лучше ноль» — возврат процентов при выполнении условий",
        weakness="Сложные условия акции; ставка вне акции высокая",
        source_url="https://www.psbank.ru/personal/loans/creditaction",
        updated_at=TODAY_ISO,
    )


def _parse_pochta_consumer_loan() -> Optional[CompetitorEntry]:
    log.info("pochta_consumer_loan: parser disabled (scaffold)")
    return None


def _parse_sovcom_halva() -> Optional[CompetitorEntry]:
    log.info("sovcom_halva: parser disabled (scaffold)")
    return None


def _parse_tbank_premium() -> Optional[CompetitorEntry]:
    log.info("tbank_premium: parser disabled (scaffold)")
    return None


# Регистр парсеров: (bank, product_key) -> callable.
# Добавляйте новые по мере готовности селекторов.
PARSERS: dict[tuple[str, str], Callable[[], Optional[CompetitorEntry]]] = {
    ("sber",   "consumer_loan"):   _parse_sber_consumer_loan,
    ("vtb",    "consumer_loan"):   _parse_vtb_consumer_loan,
    ("psb",    "consumer_loan"):   _parse_psb_military,
    ("pochta", "consumer_loan"):   _parse_pochta_consumer_loan,
    ("sovcom", "consumer_loan"):   _parse_sovcom_halva,
    ("tbank",  "premium_service"): _parse_tbank_premium,
}


# ---------------------------------------------------------------------------
# Оркестрация
# ---------------------------------------------------------------------------
def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: dict) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def refresh_matrix(data: dict) -> tuple[dict, int, int]:
    """Возвращает (обновлённый data, кол-во успехов, кол-во стейлов)."""
    matrix = data.setdefault("competitor_matrix", {})
    ok, stale = 0, 0

    for (bank, product_key), parser in PARSERS.items():
        try:
            entry = parser()
        except Exception as e:            # noqa: BLE001
            log.error("parser %s/%s raised: %s", bank, product_key, e)
            entry = None

        bucket = matrix.setdefault(product_key, [])
        # Ищем существующую запись банка в этом бакете.
        existing_idx = next(
            (i for i, e in enumerate(bucket) if e.get("bank") == bank),
            None,
        )

        if entry is None:
            # Парсер не смог — оставляем старое значение, помечаем stale.
            if existing_idx is not None:
                bucket[existing_idx]["is_stale"] = True
                stale += 1
            continue

        new_dict = asdict(entry)
        if existing_idx is None:
            bucket.append(new_dict)
        else:
            bucket[existing_idx] = new_dict
        ok += 1
        log.info("refreshed %s/%s: rate_min=%s", bank, product_key, entry.rate_min)

    data["competitor_matrix_meta"] = {
        "last_refresh_attempt": TODAY_ISO,
        "parsers_succeeded": ok,
        "parsers_stale": stale,
    }
    return data, ok, stale


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-json", type=Path, required=True)
    ap.add_argument("--registry",  type=Path, required=True)
    ap.add_argument("--output",    type=Path, required=True)
    ap.add_argument("--log-file",  type=Path, default=None)
    args = ap.parse_args()

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if args.log_file:
        handlers.append(logging.FileHandler(args.log_file, encoding="utf-8"))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )

    data = load_json(args.data_json)
    _ = load_yaml(args.registry)  # регистр пока не используется, но проверяем валидность
    data, ok, stale = refresh_matrix(data)
    save_json(args.output, data)

    log.info("done. parsers_ok=%s parsers_stale=%s", ok, stale)
    # Успехом считаем даже полный stale: файл записан, ничего не сломалось.
    # Failure только если было исключение при чтении/записи файлов.
    return 0


if __name__ == "__main__":
    sys.exit(main())
