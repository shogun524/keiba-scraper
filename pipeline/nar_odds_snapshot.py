"""
地方競馬: オッズの時系列記録 + EVの記録(締切前の10分おき実行用)。

今日の予想(scraper/scraped_data/<日付>_racecards_raw_predictions.csv)から、発走前120分以内のレースについて
オッズページ(単勝 b1・馬連 b4・ワイド b5)を取得し、
  docs/odds_history/odds_<日付>.csv に追記(最新値は latest_<日付>.csv)
  docs/ev_log/ev_<日付>.csv にその時点のEV(単勝・馬連・ワイド)を保存(発走前最後の値が残る)
する。ダッシュボード(model/generate_dashboard.py)はこれを読んで EV ボードを表示する。
ページをHTTPで取得し、表が読めない場合はその日の最初の応答を raw_<日付>_<type>.html に残す。

使い方:
    python pipeline/nar_odds_snapshot.py --date 2026-11-09 --window-min 120
"""
import argparse
import os
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ev_board import board, load_calibration  # noqa: E402
from nar_backfill import http_get  # noqa: E402
from nar_odds import ODDS_URL, parse_pair_odds, parse_win_odds  # noqa: E402

JST = ZoneInfo("Asia/Tokyo")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HIST_COLS = ["ts", "race_id", "bet", "combo", "odds", "odds_high", "pop"]


def load_today(date_str):
    path = os.path.join(ROOT, "scraper", "scraped_data", f"{date_str}_racecards_raw_predictions.csv")
    if not os.path.exists(path):
        return None
    p = pd.read_csv(path, dtype={"race_id": str}, encoding="utf-8-sig")
    return p


def to_board_frame(pred: pd.DataFrame, win_odds: dict) -> pd.DataFrame:
    """予想CSV -> ev_board が読む形(race_id, umaban, pred_win_norm, odds_win)。オッズは今取れた単勝で上書き"""
    d = pred.rename(columns={"馬番": "umaban", "p_win": "pred_win_norm"}).copy()
    d["umaban"] = pd.to_numeric(d["umaban"], errors="coerce")
    d = d[d["umaban"].notna()]
    d["odds_win"] = [win_odds.get(r, {}).get(int(u), o) for r, u, o in zip(d["race_id"], d["umaban"], d["odds"])]
    d["odds_win"] = pd.to_numeric(d["odds_win"], errors="coerce")
    return d[["race_id", "umaban", "pred_win_norm", "odds_win"]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="")
    ap.add_argument("--window-min", type=int, default=120)
    ap.add_argument("--docs", default=os.path.join(ROOT, "docs"))
    a = ap.parse_args()
    now = datetime.now(JST)
    date_str = a.date or now.strftime("%Y-%m-%d")
    pred = load_today(date_str)
    if pred is None or pred.empty:
        print(f"{date_str} の予想がないので終了")
        return 2
    pt = pred.groupby("race_id")["post_time"].first()
    targets = []
    for rid, t in pt.items():
        try:
            h, m = map(int, str(t).split(":")[:2])
        except ValueError:
            continue
        mins = (now.replace(hour=h, minute=m, second=0, microsecond=0) - now).total_seconds() / 60
        if -5 <= mins <= a.window_min:
            targets.append(rid)
    print(f"{now:%H:%M} 対象 {len(targets)}レース")
    if not targets:
        return 2

    odir = os.path.join(a.docs, "odds_history")
    os.makedirs(odir, exist_ok=True)
    ts = now.strftime("%Y-%m-%d %H:%M")
    rows, win_odds = [], {}
    for rid in targets:
        for t, bet in (("b1", "単勝"), ("b4", "馬連"), ("b5", "ワイド")):
            try:
                html = http_get(ODDS_URL.format(t=t, rid=rid))
            except Exception as e:
                print(f"  [{rid}] {bet} 取得失敗: {e}")
                continue
            if bet == "単勝":
                w = parse_win_odds(html)
                win_odds[rid] = w
                rows += [(ts, rid, bet, str(u), o, np.nan, np.nan) for u, o in w.items()]
                n = len(w)
            else:
                pr = parse_pair_odds(html)
                rows += [(ts, rid, bet, f"{x}-{y}", lo, hi if hi else np.nan, np.nan) for (x, y), (lo, hi) in pr.items()]
                n = len(pr)
            if n == 0:
                raw = os.path.join(odir, f"raw_{date_str}_{t}.html")
                if not os.path.exists(raw):
                    open(raw, "w", encoding="utf-8").write(html)
            time.sleep(0.5)
        print(f"  [{rid}] 単勝{len(win_odds.get(rid, {}))}頭")

    new = pd.DataFrame(rows, columns=HIST_COLS)
    hp = os.path.join(odir, f"odds_{date_str}.csv")
    hist = pd.concat([pd.read_csv(hp, dtype={"race_id": str, "combo": str}), new], ignore_index=True) if os.path.exists(hp) else new
    hist.to_csv(hp, index=False)
    latest = hist.sort_values("ts").groupby(["race_id", "bet", "combo"], as_index=False).last()
    latest.to_csv(os.path.join(odir, f"latest_{date_str}.csv"), index=False)

    frame = to_board_frame(pred[pred["race_id"].isin(targets)], win_odds)
    ev = board(frame, latest[latest["bet"] != "単勝"], hist, load_calibration())
    if not ev.empty:
        # 表示(券種ごとの上位)と採点(EV≧1.0)に使う行だけ残す(全組だと1日数千行になり、gitに溜まるため)
        ev["rk"] = ev.groupby(["race_id", "bet"])["ev"].rank(ascending=False, method="first")
        ev = ev[(ev["ev"] >= 0.9) | (ev["rk"] <= 5)].drop(columns="rk")
        ev["ts"] = ts
        edir = os.path.join(a.docs, "ev_log")
        os.makedirs(edir, exist_ok=True)
        ep = os.path.join(edir, f"ev_{date_str}.csv")
        if os.path.exists(ep):
            old = pd.read_csv(ep, dtype={"race_id": str, "combo": str})
            ev = pd.concat([old[~old["race_id"].isin(targets)], ev], ignore_index=True)
        ev.to_csv(ep, index=False)
    print(f"完了: オッズ {len(new)}件 / EV {len(ev)}件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
