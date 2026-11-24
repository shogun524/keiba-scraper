"""
浦和の条件別おすすめ買い目(11/25)。
距離(800 / 1300・1400 / 1500 / 2000m) × 1番人気の強さ(2倍未満 / 2〜3倍 / 3倍以上)のマスごとに、
2022〜2026年の浦和3,281レースで回収率が一番高かった買い目(model/urawa_cell_bets.json)を出す。
選び方: 的中15%以上・2022-24と2025-26の両方で、低い方の回収率が一番高いもの(券種・軸・相手 約300通りから)。
  ※候補の中から一番良いものを選んでいるので、これからの成績は表の数字より下がる見込み。
順位: 人=単勝オッズの人気順、先=過去5走の4角の位置が前の順(先行力)、騎=騎手の勝率の高い順
"""
import itertools
import json
import os

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(os.path.dirname(HERE), "model", "urawa_cell_bets.json")
try:
    with open(PATH, encoding="utf-8") as f:
        CELLS = json.load(f)
except (OSError, ValueError):
    CELLS = {}


def dcell(d):
    return {800: "800m", 1300: "1300・1400m", 1400: "1300・1400m", 1500: "1500m", 1600: "1500m", 2000: "2000m"}.get(int(d), "その他")


def fcell(fav):
    return "堅い(1番人気2倍未満)" if fav < 2 else ("ふつう(2〜3倍)" if fav < 3 else "荒れそう(3倍以上)")


def _ranks(g):
    um = pd.to_numeric(g["馬番"], errors="coerce").astype(int).values
    odds = pd.to_numeric(g["odds"], errors="coerce").values
    c4 = pd.to_numeric(g.get("mf_h5_c4_ratio", pd.Series(np.nan, index=g.index)), errors="coerce").values
    jk = pd.to_numeric(g.get("mf_jockey_win_rate", pd.Series(np.nan, index=g.index)), errors="coerce").values
    pop = [int(u) for u in um[np.argsort(odds, kind="stable")]]
    fr = [int(u) for u in um[np.argsort(np.where(np.isnan(c4), 9e9, c4), kind="stable")]]
    jr = [int(u) for u in um[np.argsort(np.where(np.isnan(jk), 9e9, -jk), kind="stable")]]
    return {"人": pop, "先": fr, "騎": jr}


def _tickets(bt, spec, rk):
    def who(h):
        k, r = h
        lst = rk[k]
        return lst[r - 1] if r - 1 < len(lst) else None
    pops = rk["人"]
    k = spec[0]
    if k == "one":
        return [str(who(spec[1]))]
    if k == "pair":
        a, b = who(spec[1]), who(spec[2])
        if a is None or b is None or a == b:
            return []
        return [f"{a}-{b}"] if bt == "馬単" else ["-".join(map(str, sorted((a, b))))]
    if k == "tri":
        t = [who(x) for x in spec[1:]]
        return [] if None in t or len(set(t)) < 3 else ["-".join(map(str, sorted(t)))]
    if k in ("jiku", "fix1", "fix2", "fix3", "multi1"):
        A = who(spec[1])
        S = [u for u in pops[spec[2] - 1:spec[3]] if u != A]
        if A is None or len(S) < 2:
            return []
        if k == "jiku":
            return ["-".join(map(str, sorted((A, x, y)))) for x, y in itertools.combinations(S, 2)]
        if k == "fix1":
            return [f"{A}-{x}-{y}" for x, y in itertools.permutations(S, 2)]
        if k == "fix2":
            return [f"{x}-{A}-{y}" for x, y in itertools.permutations(S, 2)]
        if k == "fix3":
            return [f"{x}-{y}-{A}" for x, y in itertools.permutations(S, 2)]
        return ["-".join(map(str, p)) for x, y in itertools.combinations(S, 2) for p in itertools.permutations((A, x, y))]
    if k in ("multi2", "jiku2"):
        A, B = who(spec[1]), who(spec[2])
        S = [u for u in pops[spec[3] - 1:spec[4]] if u not in (A, B)]
        if A is None or B is None or A == B or not S:
            return []
        if k == "jiku2":
            return ["-".join(map(str, sorted((A, B, x)))) for x in S]
        return ["-".join(map(str, p)) for x in S for p in itertools.permutations((A, B, x))]
    if k == "box":
        S = pops[spec[1] - 1:spec[2]]
        if bt == "3連単":
            return ["-".join(map(str, p)) for p in itertools.permutations(S, 3)]
        return ["-".join(map(str, sorted(t))) for t in itertools.combinations(S, 3)]
    return []


def _short(bt, spec, rk, tk):
    """買い目を短く: 1〜3点はそのまま、多いときは形で"""
    def who(h):
        return rk[h[0]][h[1] - 1]
    k = spec[0]
    if len(tk) <= 4:
        return " / ".join(tk)
    pops = rk["人"]
    if k in ("jiku", "fix1", "fix2", "fix3", "multi1"):
        A = who(spec[1])
        S = "・".join(str(u) for u in pops[spec[2] - 1:spec[3]] if u != A)
        return {"jiku": f"{A}軸 - {S}", "fix1": f"{A} → {S} → {S}", "fix2": f"{S} → {A} → {S}",
                "fix3": f"{S} → {S} → {A}", "multi1": f"{A}軸マルチ - {S}"}[k]
    if k in ("multi2", "jiku2"):
        A, B = who(spec[1]), who(spec[2])
        S = "・".join(str(u) for u in pops[spec[3] - 1:spec[4]] if u not in (A, B))
        return f"{A}・{B}" + (" 2頭軸マルチ - " if k == "multi2" else " 2頭軸 - ") + S
    if k == "box":
        return "・".join(map(str, pops[spec[1] - 1:spec[2]])) + " BOX"
    return " / ".join(tk[:6]) + " …"


def pick(g):
    """浦和のレース(1レース分のDataFrame)→ dict(cell, name, short, n, stats) / 対象外は None"""
    if g.empty or str(g["track"].iloc[0]) != "浦和":
        return None
    odds = pd.to_numeric(g["odds"], errors="coerce")
    g = g[odds > 0]          # 取消・除外(オッズなし)は外す
    odds = odds[odds > 0]
    if len(g) < 5:
        return dict(wait=True)
    d = pd.to_numeric(g["distance"], errors="coerce").iloc[0]
    if pd.isna(d):
        return None
    key = f"{dcell(d)}|{fcell(float(odds.min()))}"
    c = CELLS.get(key)
    if not c:
        return dict(cell=key.replace("|", "・"), none=True)
    spec = [tuple(x) if isinstance(x, list) else x for x in c["spec"]]
    rk = _ranks(g)
    tk = _tickets(c["bet_type"], spec, rk)
    if not tk:
        return dict(cell=key.replace("|", "・"), name=c["name"], overlap=True)
    return dict(cell=key.replace("|", "・"), name=c["name"], bet_type=c["bet_type"], tickets=tk, short=_short(c["bet_type"], spec, rk, tk), stats=c)


def html(g):
    p = pick(g)
    if not p:
        return ""
    if p.get("wait"):
        return '<p class="urawa" style="margin:6px 0 2px;padding:6px 8px;background:#FFF6E0;border-left:3px solid #C98A00;font-size:.82rem;line-height:1.55;">浦和の条件別おすすめ：オッズ待ち</p>'
    if p.get("none"):
        return f'<p class="urawa" style="margin:6px 0 2px;padding:6px 8px;background:#FFF6E0;border-left:3px solid #C98A00;font-size:.82rem;line-height:1.55;">浦和の条件別おすすめ（{p["cell"]}）：この条件は過去の数が少ないので出していません</p>'
    if p.get("overlap"):
        return (f'<p class="urawa" style="margin:6px 0 2px;padding:6px 8px;background:#FFF6E0;border-left:3px solid #C98A00;font-size:.82rem;line-height:1.55;">浦和の条件別おすすめ（{p["cell"]}）：{p["name"]} … 今回は同じ馬が重なるので買い目なし</p>')
    s = p["stats"]
    return (f'<p class="urawa" style="margin:6px 0 2px;padding:6px 8px;background:#FFF6E0;border-left:3px solid #C98A00;font-size:.82rem;line-height:1.55;">浦和の条件別おすすめ（{p["cell"]}）：<b>{p["bet_type"]} {p["short"]}</b>（{len(p["tickets"])}点）'
            f'<br><small>{s["name"]}。過去{s["races"]}レースで的中{s["hit"]:.0%}・回収率{s["roi"]:.0%}'
            f'（2022-24年 {s["roi_a"]:.0%}／2025-26年 {s["roi_b"]:.0%}）</small></p>')
