"""
地方競馬: 過去レースの3連単の最終オッズ(人気上位300組)を nar.netkeiba から取って貯める。

nar.netkeiba の3連単オッズ「人気順」(odds_get_form.html?type=b8&housiki=c99&ninki=0/100/200)は、
終わったレースでも最終オッズが表示される(2026-11-15 の診断で 2023年のレースまで確認)。1ページ100組。

出力(--out のフォルダ):
  nar_tri_odds.csv.gz  race_id, combo(1着-2着-3着), odds, ninki   (追記)
  nar_tri_done.json    取り終えたレースID → 取れた組数(0 = オッズなし)

使い方:
  python pipeline/nar_tri_backfill.py data/nar_results.csv data/ --since 2025-01-01 --minutes 320
"""
import argparse
import gzip
import json
import os
import random
import re
import sys
import time

import pandas as pd
import requests

URL = "https://nar.netkeiba.com/odds/odds_get_form.html?type=b8&race_id={rid}&housiki=c99&ninki={n}"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
ROW = re.compile(r'<td class="Ninki">\s*(\d+)\s*</td>.*?<ul class="fc">(.*?)</ul>.*?<td class="Name_Odds">\s*([\d,.]+)\s*</td>', re.S)
PAGES = (0, 100, 200)


def parse(html):
    out = []
    for nk, ul, od in ROW.findall(html):
        nums = re.findall(r'<span class="UmaBan">\s*(\d+)\s*</span>', ul)
        if len(nums) == 3:
            try:
                out.append(("-".join(nums), float(od.replace(",", "")), int(nk)))
            except ValueError:
                pass
    return out


def fetch_race(S, rid):
    rows = []
    for n in PAGES:
        for k in range(3):
            try:
                r = S.get(URL.format(rid=rid, n=n), timeout=20,
                          headers={"Referer": f"https://nar.netkeiba.com/odds/index.html?type=b8&race_id={rid}"})
                r.encoding = r.apparent_encoding if r.encoding in (None, "ISO-8859-1") else r.encoding
                h = r.text
                break
            except requests.RequestException:
                time.sleep(5 * (k + 1))
        else:
            return None   # 通信エラー(次回やり直す)
        got = parse(h)
        if not got and n == 0 and not getattr(fetch_race, "dumped", False):
            fetch_race.dumped = True
            open(os.path.join(os.environ.get("TRI_OUT", "."), "raw_sample.html"), "w", encoding="utf-8").write(h)
            print(f"[DEBUG] {rid} status={r.status_code} len={len(h)} head={h[:300]!r}", flush=True)
        rows += got
        time.sleep(random.uniform(0.7, 1.1))
        if len(got) < 100:
            break
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results_csv")
    ap.add_argument("out")
    ap.add_argument("--since", default="2025-01-01")
    ap.add_argument("--minutes", type=float, default=320)
    a = ap.parse_args()
    t_end = time.time() + a.minutes * 60
    done_p = os.path.join(a.out, "nar_tri_done.json")
    odds_p = os.path.join(a.out, "nar_tri_odds.csv.gz")
    done = json.load(open(done_p)) if os.path.exists(done_p) else {}
    r = pd.read_csv(a.results_csv, usecols=["race_id", "race_date"], dtype=str).drop_duplicates("race_id")
    todo = sorted(set(r.loc[r.race_date >= a.since, "race_id"]) - set(done), reverse=True)   # 新しいレースから
    print(f"[INFO] 対象 {len(todo)}レース(取り終え {len(done)})", flush=True)
    S = requests.Session()
    S.headers.update({"User-Agent": UA, "Accept-Language": "ja"})
    new = not os.path.exists(odds_p)
    n_ok = 0
    with gzip.open(odds_p, "at", encoding="utf-8") as f:
        if new:
            f.write("race_id,combo,odds,ninki\n")
        for i, rid in enumerate(todo):
            if time.time() > t_end:
                break
            rows = fetch_race(S, rid)
            if rows is None:
                continue
            for c, o, nk in rows:
                f.write(f"{rid},{c},{o},{nk}\n")
            done[rid] = len(rows)
            n_ok += bool(rows)
            if i % 200 == 0:
                f.flush()
                json.dump(done, open(done_p, "w"))
                print(f"  {i}/{len(todo)} レース(オッズあり {n_ok})", flush=True)
    json.dump(done, open(done_p, "w"))
    left = len(todo) - sum(1 for x in todo if x in done)
    print(f"[INFO] 今回 {n_ok}レース分を取得。残り {left}レース", flush=True)
    open(os.path.join(a.out, "nar_tri_left.txt"), "w").write(str(left))


if __name__ == "__main__":
    sys.exit(main())
