"""
地方競馬のオッズ取得(nar.netkeiba のオッズページ)。

JRAと違ってオッズ用のJSON APIは呼ばれておらず、オッズページ(odds/index.html)の表に値が入っている
(2026-11 の診断で確認)。
  type=b1: 単勝の表(枠・馬番・印・馬名・オッズ)と複勝の表(オッズが "1.8 - 3.2" の幅)
  type=b4: 馬連。1頭目ごとに表があり、見出しが1頭目の馬番、各行が「2頭目の馬番・オッズ」
  type=b5: ワイド。同じ形で、オッズが "4.9 - 5.4" の幅
取消の馬は「取消」と入る。
"""
import io
import re

import pandas as pd

ODDS_URL = "https://nar.netkeiba.com/odds/index.html?type={t}&race_id={rid}"


def _range(v):
    """'4.9 - 5.4' -> (4.9, 5.4) / '12.7' -> (12.7, None) / '取消' -> (None, None)"""
    nums = re.findall(r"\d+(?:\.\d+)?", str(v).replace(",", ""))
    if not nums:
        return None, None
    lo = float(nums[0])
    hi = float(nums[1]) if len(nums) > 1 else None
    return lo, hi


def _col(df, key):
    for c in df.columns:
        if key in re.sub(r"\s", "", str(c)):
            return c
    return None


def parse_win_odds(html: str) -> dict:
    """単勝 {馬番: オッズ}。b1ページの最初の「馬番・オッズ」表(幅でない方)"""
    for t in pd.read_html(io.StringIO(html)):
        cu, co = _col(t, "馬番"), _col(t, "オッズ")
        if cu is None or co is None:
            continue
        vals = t[co].astype(str)
        if vals.str.contains(r"\d+(?:\.\d+)?\s*-\s*\d", regex=True).any():
            continue  # 複勝(幅)の表
        out = {}
        for u, v in zip(t[cu], vals):
            lo, _ = _range(v)
            try:
                u = int(u)
            except (TypeError, ValueError):
                continue
            if lo:
                out[u] = lo
        if out:
            return out
    return {}


def parse_pair_odds(html: str) -> dict:
    """馬連・ワイド {(a, b): (オッズ, 上限)}。1頭目ごとの小さな表(3列: 見出し=1頭目, 2頭目, オッズ)を全部読む"""
    out = {}
    for t in pd.read_html(io.StringIO(html)):
        if t.shape[1] < 2:
            continue
        try:
            first = int(str(t.columns[0]).split(".")[0])
        except ValueError:
            continue
        for _, r in t.iterrows():
            try:
                second = int(r.iloc[0])
            except (TypeError, ValueError):
                continue
            lo, hi = _range(r.iloc[1])
            if lo is None or first == second or not (1 <= first <= 18 and 1 <= second <= 18):
                continue
            out[(min(first, second), max(first, second))] = (lo, hi)
    return out
