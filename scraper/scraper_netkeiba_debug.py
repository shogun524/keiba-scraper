"""
南関東(大井・船橋・浦和・川崎)出馬表スクレイパー - netkeiba版(診断用)

前回まで全リクエストがタイムアウトしていた原因を特定するため、失敗時に
スクリーンショットとHTTPステータスをアーティファクトとして保存するようにした。
"""
import time
import random
import json
import logging
import re
import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("nar_netkeiba_scraper")

TRACK_CODES = {"浦和": "42", "船橋": "43", "大井": "44", "川崎": "45"}
BASE_URL = "https://nar.netkeiba.com/race/newspaper.html"
REQUEST_INTERVAL_SEC = (3.0, 6.0)
MAX_RACES_PER_DAY = 12

OUTPUT_DIR = Path("scraped_data")
OUTPUT_DIR.mkdir(exist_ok=True)
DEBUG_DIR = Path("debug_screenshots")
DEBUG_DIR.mkdir(exist_ok=True)


def build_race_id(date: datetime.date, track: str, race_num: int) -> str:
    jyo_cd = TRACK_CODES[track]
    return f"{date.year}{jyo_cd}{date.month:02d}{date.day:02d}{race_num:02d}"


def scrape_race(page, race_id: str, debug_first: bool = False) -> str | None:
    """1レース分のページをレンダリングしてテキスト化する"""
    url = f"{BASE_URL}?race_id={race_id}"
    response = None
    try:
        response = page.goto(url, timeout=45000, wait_until="load")
        page.wait_for_timeout(3000)
    except Exception as e:
        logger.warning(f"読み込み失敗: {url} - {e}")
        if debug_first:
            try:
                page.screenshot(path=str(DEBUG_DIR / f"fail_{race_id}.png"), full_page=True)
                logger.info(f"  -> 失敗時のスクリーンショット保存: debug_screenshots/fail_{race_id}.png")
            except Exception as se:
                logger.warning(f"  スクリーンショット保存も失敗: {se}")
        return None

    status = response.status if response else None
    logger.info(f"  HTTPステータス: {status}")

    if debug_first:
        try:
            page.screenshot(path=str(DEBUG_DIR / f"ok_{race_id}.png"), full_page=True)
            logger.info(f"  -> 成功時のスクリーンショット保存: debug_screenshots/ok_{race_id}.png")
        except Exception as se:
            logger.warning(f"  スクリーンショット保存失敗: {se}")

    body_text = page.inner_text("body")
    if debug_first:
        logger.info(f"  取得した本文の先頭300字: {body_text[:300]!r}")

    if "empty paramter" in body_text or len(body_text) < 500:
        return None
    if "レース前日14時頃公開です" in body_text:
        return None
    if not re.search(r'^\d{1,2}\n\d{1,2}\n--$', body_text, re.MULTILINE):
        return None
    return body_text


def scrape_day(date: datetime.date, tracks: list[str] | None = None):
    tracks = tracks or list(TRACK_CODES.keys())
    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
            viewport={"width": 1280, "height": 1000},
        )
        page = context.new_page()

        first_request = True
        for track in tracks:
            for race_num in range(1, MAX_RACES_PER_DAY + 1):
                race_id = build_race_id(date, track, race_num)
                logger.info(f"取得中: {date} {track} {race_num}R (race_id={race_id})")
                text = scrape_race(page, race_id, debug_first=first_request)
                first_request = False
                if text:
                    results.append({"date": str(date), "track": track, "race_num": race_num,
                                     "race_id": race_id, "raw_text": text})
                else:
                    logger.info("  -> データ無し、または該当レース無し")
                time.sleep(random.uniform(*REQUEST_INTERVAL_SEC))

        browser.close()

    out_path = OUTPUT_DIR / f"{date}_racecards_raw.jsonl"
    with open(out_path, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    logger.info(f"保存: {out_path} ({len(results)}レース)")
    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="南関東出馬表スクレイパー(netkeiba版・診断用)")
    parser.add_argument("--date", default=(datetime.date.today() + datetime.timedelta(days=1)).isoformat(),
                         help="取得対象日(YYYY-MM-DD)。デフォルトは翌日")
    parser.add_argument("--tracks", nargs="+", default=list(TRACK_CODES.keys()))
    args, _unknown = parser.parse_known_args()

    target_date = datetime.date.fromisoformat(args.date)
    scrape_day(target_date, args.tracks)
