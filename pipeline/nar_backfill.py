"""
地方競馬の過去結果+払戻のバックフィル(nar.netkeiba.com)。

日付ごとにレース一覧(race_list_sub.html、JSなしでレースIDが入っている)を取り、
各レースの結果ページ(result.html)から 結果表・コーナー通過順・レース情報・払戻表 を取る。
1ページで結果と払戻の両方が取れるので、アクセスは「1レース1回」で済む。ブラウザは使わない(HTTPのみ)。

出力(--out-dir、追記):
  nar_results.csv : 1頭1行(着順・人気・単勝・馬体重・上り・通過順・騎手・調教師・距離・馬場・1着賞金 など)
  nar_payouts.csv : 払戻 1組1行(単勝〜3連単)
  nar_progress.json / nar_dates_done.json / nar_zero_tries.json : 再開用の進捗

使い方:
  python pipeline/nar_backfill.py 2022-01-01 2026-11-08 --out-dir data --workers 3 --max-minutes 300
終了コード: 0=期間をすべて処理 / 3=時間切れ・取りこぼしあり(再実行で続きから)
"""
import argparse
import csv
import json
import os
import random
import re
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from race_page import (BANEI_TRACK, PAYOUT_COLUMNS, parse_nar_meta, parse_payouts,  # noqa: E402
                       parse_race_result)

LIST_URL = "https://nar.netkeiba.com/top/race_list_sub.html?kaisai_date={d}"
RESULT_URL = "https://nar.netkeiba.com/race/result.html?race_id={rid}"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

RESULT_COLUMNS = [
    "race_id", "race_date", "track_code", "track", "race_no", "post_time", "surface", "distance", "weather", "baba",
    "race_name", "race_data2", "head_count", "prize1", "class_text", "is_graded",
    "finish", "waku", "umaban", "horse", "sex", "age", "weight_carry", "jockey", "trainer", "time", "margin",
    "popularity", "odds", "last3f", "horse_weight", "weight_diff", "c1", "c2", "c3", "c4",
]
ZERO_TRIES_LIMIT = 3
FAIL_STREAK_LIMIT = 30


def http_get(url, referer="https://nar.netkeiba.com/", timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": referer, "Accept-Language": "ja"})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        raw = res.read()
        ctype = res.headers.get("Content-Type", "")
    m = re.search(r"charset=([\w-]+)", ctype) or re.search(rb'charset="?([\w-]+)', raw[:3000])
    enc = (m.group(1).decode() if isinstance(m.group(1), bytes) else m.group(1)) if m else "euc-jp"
    try:
        return raw.decode(enc)
    except (LookupError, UnicodeDecodeError):
        return raw.decode("euc-jp", errors="replace")


def race_ids_for_date(d: str) -> list[str]:
    html = http_get(LIST_URL.format(d=d))
    ids = sorted(set(re.findall(r"race_id=(\d{12})", html)))
    return [i for i in ids if i[4:6] != BANEI_TRACK and i[6:10] == d[4:8]]


def _to_int(v):
    m = re.match(r"\s*(\d+)", str(v))
    return int(m.group(1)) if m else None


def fetch_race(rid: str):
    html = http_get(RESULT_URL.format(rid=rid))
    rows = parse_race_result(html, rid)
    if not rows or not any(_to_int(r.get("着順")) == 1 for r in rows):
        raise ValueError("結果が確定していない/結果表なし")
    meta = parse_nar_meta(html, rid)
    out = []
    for r in rows:
        out.append({
            **{k: meta.get(k) for k in ["race_id", "race_date", "track_code", "track", "race_no", "post_time", "surface",
                                       "distance", "weather", "baba", "race_name", "race_data2", "head_count", "prize1",
                                       "class_text", "is_graded"]},
            "finish": _to_int(r.get("着順")), "waku": r.get("枠番"), "umaban": _to_int(r.get("馬番")),
            "horse": r.get("馬名"), "sex": r.get("性別"), "age": r.get("馬齢"), "weight_carry": r.get("斤量"),
            "jockey": r.get("騎手"), "trainer": r.get("調教師"), "time": r.get("タイム"), "margin": r.get("着差"),
            "popularity": _to_int(r.get("人気")), "odds": r.get("単勝"), "last3f": r.get("上り"),
            "horse_weight": r.get("馬体重"), "weight_diff": r.get("場体重増減"),
            "c1": r.get("1コーナー"), "c2": r.get("2コーナー"), "c3": r.get("3コーナー"), "c4": r.get("4コーナー"),
        })
    return out, parse_payouts(html, rid)


def _load(path, default):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def _save(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("start")
    ap.add_argument("end")
    ap.add_argument("--out-dir", default="data")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--max-minutes", type=float, default=None)
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    res_path = os.path.join(a.out_dir, "nar_results.csv")
    pay_path = os.path.join(a.out_dir, "nar_payouts.csv")
    prog_path = os.path.join(a.out_dir, "nar_progress.json")
    dates_path = os.path.join(a.out_dir, "nar_dates_done.json")
    zero_path = os.path.join(a.out_dir, "nar_zero_tries.json")
    done = set(_load(prog_path, []))
    dates_done = set(_load(dates_path, []))
    zero_tries = _load(zero_path, {})

    new_res = not os.path.exists(res_path)
    new_pay = not os.path.exists(pay_path)
    fr = open(res_path, "a", newline="", encoding="utf-8")
    fp = open(pay_path, "a", newline="", encoding="utf-8")
    wr = csv.DictWriter(fr, fieldnames=RESULT_COLUMNS, extrasaction="ignore")
    wp = csv.DictWriter(fp, fieldnames=PAYOUT_COLUMNS)
    if new_res:
        wr.writeheader()
    if new_pay:
        wp.writeheader()
    lock = threading.Lock()
    t0 = time.time()
    stats = {"ok": 0, "err": 0, "streak": 0}
    finished = True
    stop = False

    d0, d1 = date.fromisoformat(a.start), date.fromisoformat(a.end)
    dates = [(d0 + timedelta(days=i)).strftime("%Y%m%d") for i in range((d1 - d0).days + 1)]
    print(f"期間 {a.start}〜{a.end}({len(dates)}日)、処理済み {len(dates_done)}日・{len(done)}レース", flush=True)

    def work(rid):
        for attempt in range(3):
            try:
                rows, pays = fetch_race(rid)
                with lock:
                    for r in rows:
                        wr.writerow(r)
                    for p in pays:
                        wp.writerow(p)
                    fr.flush()
                    fp.flush()
                    done.add(rid)
                    stats["ok"] += 1
                    stats["streak"] = 0
                time.sleep(random.uniform(0.3, 0.8))
                return True
            except Exception as e:
                if attempt == 2:
                    with lock:
                        stats["err"] += 1
                        stats["streak"] += 1
                    print(f"  [{rid}] 失敗: {e}", flush=True)
                    return False
                time.sleep(2 * (attempt + 1))

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        for d in dates:
            if d in dates_done:
                continue
            if a.max_minutes and (time.time() - t0) / 60 > a.max_minutes:
                print(f"!! 制限時間({a.max_minutes:.0f}分)に達したので {d} の手前で中断", flush=True)
                finished = False
                break
            if stats["streak"] >= FAIL_STREAK_LIMIT:
                print("!! 失敗が続いたので中断(アクセス制限の可能性)。次の実行で続きから", flush=True)
                finished = False
                break
            try:
                ids = race_ids_for_date(d)
            except Exception as e:
                print(f"[{d}] 一覧の取得失敗: {e}", flush=True)
                finished = False
                stats["streak"] += 1
                continue
            if not ids:
                # 地方は毎日どこかで開催があることが多いが、無い日もある(年末年始など)。
                # 3回の実行で毎回0件なら開催なしとみなす
                zero_tries[d] = zero_tries.get(d, 0) + 1
                _save(zero_path, zero_tries)
                if zero_tries[d] >= ZERO_TRIES_LIMIT:
                    dates_done.add(d)
                    _save(dates_path, sorted(dates_done))
                else:
                    finished = False
                continue
            todo = [r for r in ids if r not in done]
            if todo:
                list(ex.map(work, todo))
            _save(prog_path, sorted(done))
            if all(r in done for r in ids):
                dates_done.add(d)
                _save(dates_path, sorted(dates_done))
            else:
                finished = False
            el = (time.time() - t0) / 60
            print(f"[{d}] {len(ids)}レース(新規{len(todo)}) 累計 成功={stats['ok']} 失敗={stats['err']} {el:.0f}分", flush=True)
    fr.close()
    fp.close()
    _save(prog_path, sorted(done))
    _save(dates_path, sorted(dates_done))
    if stats["err"]:
        finished = False
    print(f"{'完了' if finished else '途中終了'}。成功={stats['ok']} 失敗={stats['err']}", flush=True)
    sys.exit(0 if finished else 3)


if __name__ == "__main__":
    main()
