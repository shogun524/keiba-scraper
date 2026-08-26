"""
締切(発走時刻)が近いレースだけを再スクレイピングして、オッズ/人気を最新化する。

2026年8月改訂版モデルは「現在レースの人気」を主要な予測因子として使うため、
この再取得は単なる表示更新ではなく、予測精度そのものに直結する。

10分おきに実行される想定。今日すでに取得済みの出馬表(jsonl)を読み、各レースの
発走時刻を調べて「今から --window-min 分以内に発走する」レースだけ再取得する。
再取得したデータで jsonl を更新する(predict.py / generate_dashboard.py の再実行は
ワークフロー側で行う)。
"""
import argparse
import datetime
import json
import re
import time
import random
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).parent))
from scraper_netkeiba import scrape_race  # noqa: E402

JST = ZoneInfo("Asia/Tokyo")
OUTPUT_DIR = Path("scraped_data")


def extract_post_time(raw_text: str) -> str | None:
    """出馬表テキストから発走時刻(HH:MM)を抜き出す。predict.pyのguess_race_metaと同じ正規表現。"""
    m = re.search(r'\n\d+R\n[^\n]+\n(\d{2}:\d{2})発走', raw_text)
    return m.group(1) if m else None


def is_near_deadline(post_time_str: str, now: datetime.datetime, window_min: int) -> bool:
    """発走時刻が『今から window_min 分以内、かつまだ発走前』かどうかを判定する。"""
    try:
        h, m = map(int, post_time_str.split(":"))
    except (ValueError, AttributeError):
        return False
    post_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
    delta_min = (post_dt - now).total_seconds() / 60
    return 0 <= delta_min <= window_min


def rescrape_near_deadline(date_str: str, window_min: int = 10):
    jsonl_path = OUTPUT_DIR / f"{date_str}_racecards_raw.jsonl"
    if not jsonl_path.exists():
        print(f"対象ファイルが無いためスキップ: {jsonl_path}")
        return

    with open(jsonl_path, encoding="utf-8") as f:
        records = [json.loads(line) for line in f if line.strip()]

    now = datetime.datetime.now(JST)
    targets = []
    for rec in records:
        post_time = extract_post_time(rec["raw_text"])
        if post_time and is_near_deadline(post_time, now, window_min):
            targets.append((rec, post_time))

    if not targets:
        print(f"締切{window_min}分以内のレースはありませんでした({now.strftime('%H:%M')}時点)。")
        return

    print(f"締切間近のレース {len(targets)}件を再取得します: "
          + ", ".join(f"{r['track']}{r['race_num']}R({t}発走)" for r, t in targets))

    updated = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
            viewport={"width": 1280, "height": 1000},
        )
        page = context.new_page()
        for rec, post_time in targets:
            text = scrape_race(page, rec["race_id"])
            if text:
                updated[rec["race_id"]] = text
                print(f"  更新: {rec['track']}{rec['race_num']}R")
            else:
                print(f"  取得失敗(前回のデータを維持): {rec['track']}{rec['race_num']}R")
            time.sleep(random.uniform(2.0, 4.0))
        browser.close()

    if not updated:
        return

    with open(jsonl_path, "w", encoding="utf-8") as f:
        for rec in records:
            if rec["race_id"] in updated:
                rec["raw_text"] = updated[rec["race_id"]]
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"保存: {jsonl_path} ({len(updated)}件更新)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="締切間近レースの再スクレイピング")
    parser.add_argument("--date", default=datetime.date.today().isoformat())
    parser.add_argument("--window-min", type=int, default=10,
                         help="発走何分前までを『締切間近』とみなすか")
    args, _unknown = parser.parse_known_args()

    rescrape_near_deadline(args.date, args.window_min)
