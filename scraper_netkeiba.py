"""
南関東(大井・船橋・浦和・川崎)出馬表スクレイパー - netkeiba版

確認済み事項:
- nar.netkeiba.com/race/newspaper.html は robots.txt で禁止されていない
  (2026-08-13 時点でAnthropicのfetchツールにより確認。ただし今後変更される
  可能性があるので、本番運用前に https://nar.netkeiba.com/robots.txt を
  直接確認してください)
- race_id 形式: {年4桁}{場コード2桁}{月日4桁}{レース番号2桁} (計12桁)
  南関東の場コード: 浦和=42, 船橋=43, 大井=44, 川崎=45
- ページ本体はJavaScriptで描画されるため、単純なrequests.get()では
  出馬表テーブルの中身が取得できない。Playwright等でレンダリング後の
  DOMを取得する必要がある。

未確認事項(要テスト):
- newspaper.html / shutuba_past.html のどちらが目的のデータに最適か
  (前者は「競馬新聞」形式、後者は「馬柱」形式。添付いただいたサンプルは
  前者に近い構造だったため、まずnewspaper.htmlを対象にしています)
- 実際にPlaywrightでレンダリングした際のテーブル構造・CSSセレクタ
"""
import time
import random
import logging
import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("nar_netkeiba_scraper")

TRACK_CODES = {"浦和": "42", "船橋": "43", "大井": "44", "川崎": "45"}
BASE_URL = "https://nar.netkeiba.com/race/newspaper.html"
REQUEST_INTERVAL_SEC = (3.0, 6.0)  # サーバー負荷を避けるため間隔を空ける(競輪スクレイパーと同様の礼儀)
MAX_RACES_PER_DAY = 12

OUTPUT_DIR = Path("scraped_data")
OUTPUT_DIR.mkdir(exist_ok=True)


def build_race_id(date: datetime.date, track: str, race_num: int) -> str:
    """race_id を組み立てる。ただし場コードだけでは開催回・日目が一意に決まらないため、
    実際には該当日にその場が開催されているかを事前に race_list.html 等で確認する必要がある
    (本雛形では単純化のため date から直接組み立てているが、要検証)。
    """
    jyo_cd = TRACK_CODES[track]
    return f"{date.year}{jyo_cd}{date.month:02d}{date.day:02d}{race_num:02d}"


def scrape_race(page, race_id: str) -> str | None:
    """1レース分のページをレンダリングしてテキスト化する"""
    url = f"{BASE_URL}?race_id={race_id}"
    try:
        page.goto(url, timeout=20000, wait_until="networkidle")
    except Exception as e:
        logger.warning(f"読み込み失敗: {url} - {e}")
        return None

    # 出馬表テーブルが存在しない(該当レース無し)場合は早期リターン
    # 要検証: 実際の「レース無し」時の画面表示・セレクタを確認して判定条件を調整する
    body_text = page.inner_text("body")
    if "empty paramter" in body_text or len(body_text) < 500:
        return None
    return body_text


def scrape_day(date: datetime.date, tracks: list[str] | None = None):
    tracks = tracks or list(TRACK_CODES.keys())
    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
            viewport={"width": 1280, "height": 1000},
        )
        page = context.new_page()

        for track in tracks:
            for race_num in range(1, MAX_RACES_PER_DAY + 1):
                race_id = build_race_id(date, track, race_num)
                logger.info(f"取得中: {date} {track} {race_num}R (race_id={race_id})")
                text = scrape_race(page, race_id)
                if text:
                    results.append({"date": str(date), "track": track, "race_num": race_num,
                                     "race_id": race_id, "raw_text": text})
                else:
                    logger.info(f"  -> データ無し、または該当レース無し")
                time.sleep(random.uniform(*REQUEST_INTERVAL_SEC))

        browser.close()

    out_path = OUTPUT_DIR / f"{date}_racecards_raw.jsonl"
    import json
    with open(out_path, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    logger.info(f"保存: {out_path} ({len(results)}レース)")
    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="南関東出馬表スクレイパー(netkeiba版)")
    parser.add_argument("--date", default=(datetime.date.today() + datetime.timedelta(days=1)).isoformat(),
                         help="取得対象日(YYYY-MM-DD)。デフォルトは翌日")
    parser.add_argument("--tracks", nargs="+", default=list(TRACK_CODES.keys()))
    args = parser.parse_args()

    target_date = datetime.date.fromisoformat(args.date)
    scrape_day(target_date, args.tracks)
