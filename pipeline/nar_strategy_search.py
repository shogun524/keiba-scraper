"""
地方競馬: AIを使った買い方の総当たり探索(組み方 × 買うレースの条件)。JRA の strategy_search.py と同じ方式。

1. 各レースについて、組み方(券種と買い目の作り方)ごとに「点数」と「払戻」を計算する
2. 買う時点で分かる情報だけでレースを絞る条件(AIの自信度・◎の人気・AIと市場のずれ・頭数・賞金・競馬場など)を作る
3. 「組み方 × 条件(1つ or 2つの組み合わせ)」の回収率を、選定期間で計算し、検証期間で確かめる

使い方:
    python pipeline/nar_strategy_search.py data/nar_wf_preds.parquet data/nar_payouts.csv \
        --select-until 2026-01-01 --out data/nar_strategy_search.csv

preds(nar_train.py の --wf-out)の列: race_id, race_date, track_code, umaban, popularity, odds, ai_win, ai_rank,
field_size, log_prize1, distance
(odds・popularity は確定値なので、実際に買う時点とは多少ずれる)
"""
import argparse
from itertools import combinations

import numpy as np
import pandas as pd

MINAMI_KANTO = {"42", "43", "44", "45"}  # 浦和・船橋・大井・川崎


def _key(bet, horses):
    if bet in ("馬連", "ワイド", "3連複"):
        horses = sorted(horses)
    return "-".join(str(int(h)) for h in horses)


def box(bet, hs, k):
    return [(bet, _key(bet, c)) for c in combinations(hs, k)]


def axis_flow(bet, axis, others, k):
    """軸1頭 + 相手から(k-1)頭"""
    return [(bet, _key(bet, (axis,) + c)) for c in combinations([o for o in others if o != axis], k - 1)]


def formation3(bet, first, second, third):
    out = set()
    for a in first:
        for b in second:
            for c in third:
                if len({a, b, c}) == 3:
                    out.add((bet, _key(bet, (a, b, c))))
    return sorted(out)


def structures(A, M, value):
    """組み方 -> 買い目リスト。A=AI順の馬番, M=人気順の馬番, value=AI1着率÷市場確率が最大の馬(AI上位5頭から)"""
    a1, a2 = A[0], A[1]
    return {
        "単勝 ◎": [("単勝", _key("単勝", [a1]))],
        "単勝 妙味馬": [("単勝", _key("単勝", [value]))],
        "複勝 ◎": [("複勝", _key("複勝", [a1]))],
        "複勝 妙味馬": [("複勝", _key("複勝", [value]))],
        "ワイド ◎-○": [("ワイド", _key("ワイド", [a1, a2]))],
        "ワイド ◎-AI2,3": axis_flow("ワイド", a1, A[:3], 2),
        "ワイド ◎-AI2〜4": axis_flow("ワイド", a1, A[:4], 2),
        "ワイド AI上位3頭BOX": box("ワイド", A[:3], 2),
        "ワイド ◎-1〜3人気": axis_flow("ワイド", a1, [m for m in M if m != a1][:3] + [a1], 2),
        "ワイド 妙味馬-AI上位2頭": axis_flow("ワイド", value, [x for x in A if x != value][:2] + [value], 2),
        "馬連 ◎-○": [("馬連", _key("馬連", [a1, a2]))],
        "馬連 ◎-AI2〜4": axis_flow("馬連", a1, A[:4], 2),
        "馬連 AI上位3頭BOX": box("馬連", A[:3], 2),
        "馬連 AI上位4頭BOX": box("馬連", A[:4], 2),
        "馬単 ◎→AI2〜4": [("馬単", _key("馬単", [a1, x])) for x in A[1:4]],
        "3連複 AI上位3頭BOX": box("3連複", A[:3], 3),
        "3連複 AI上位4頭BOX": box("3連複", A[:4], 3),
        "3連複 AI上位5頭BOX": box("3連複", A[:5], 3),
        "3連複 ◎軸-AI2〜5": axis_flow("3連複", a1, A[:5], 3),
        "3連複 ◎軸-AI2〜6": axis_flow("3連複", a1, A[:6], 3),
        "3連複 ◎軸-AI2〜7": axis_flow("3連複", a1, A[:7], 3),
        "3連複 ◎○2頭軸-AI3〜8": [("3連複", _key("3連複", (a1, a2, x))) for x in A[2:8]],
        "3連複 ◎-AI2,3-AI2〜6": formation3("3連複", [a1], A[1:3], A[1:6]),
        "3連複 ◎軸-1〜5人気": axis_flow("3連複", a1, [m for m in M if m != a1][:5] + [a1], 3),
        "3連単 ◎→○→AI3": [("3連単", _key("3連単", A[:3]))],
        "3連単 ◎→AI2,3→AI2〜5": [("3連単", _key("3連単", (a1, b, c))) for b in A[1:3] for c in A[1:5] if c != b],
        "3連単 ◎→AI2〜4→AI2〜6": [("3連単", _key("3連単", (a1, b, c))) for b in A[1:4] for c in A[1:6] if c != b],
        "3連単 ◎,○→◎,○→AI3〜6": [("3連単", _key("3連単", (x, y, c))) for x, y in [(a1, a2), (a2, a1)] for c in A[2:6]],
    }


def race_table(preds: pd.DataFrame, pay: dict):
    recs, feats = [], []
    for rid, g in preds.groupby("race_id", sort=False):
        if len(g) < 6 or g["popularity"].isna().any() or g["odds"].isna().any() or (g["odds"] <= 0).any():
            continue
        g = g.sort_values("ai_rank")
        A = g["umaban"].astype(int).tolist()
        M = g.sort_values(["popularity", "umaban"])["umaban"].astype(int).tolist()
        inv = 1 / g["odds"].to_numpy(dtype=float)
        p_mkt = inv / inv.sum()
        ai = g["ai_win"].to_numpy() / g["ai_win"].sum()
        ratio = ai / p_mkt
        value = A[int(np.argmax(ratio[:5]))]
        top = g.iloc[0]
        feats.append(dict(
            race_id=rid, race_date=top["race_date"], track_code=str(top["track_code"]).zfill(2),
            ai1_win=ai[0], ai_gap=ai[0] - ai[1],
            ai1_pop=top["popularity"], ai1_odds=top["odds"], ai1_ratio=ratio[0],
            ai_top3_in_pop5=sum(p <= 5 for p in g.iloc[:3]["popularity"]),
            field_size=len(g), prize=np.exp(top["log_prize1"]) if pd.notna(top["log_prize1"]) else np.nan,
            distance=top["distance"], fav_odds=g["odds"].min(),
        ))
        for name, tickets in structures(A, M, value).items():
            if tickets:
                recs.append((rid, name, len(tickets), sum(pay.get((rid, b, c), 0) for b, c in tickets)))
    return pd.DataFrame(recs, columns=["race_id", "structure", "n", "ret"]), pd.DataFrame(feats).set_index("race_id")


def conditions(F: pd.DataFrame) -> dict:
    mk = F.track_code.isin(MINAMI_KANTO)
    q = F.prize.quantile([0.33, 0.67]).to_list()
    return {
        "全レース": pd.Series(True, index=F.index),
        "◎1着率40%以上": F.ai1_win >= 0.40, "◎1着率25〜40%": F.ai1_win.between(0.25, 0.40), "◎1着率25%未満": F.ai1_win < 0.25,
        "◎と○の差15pt以上": F.ai_gap >= 0.15, "◎と○の差5pt未満": F.ai_gap < 0.05,
        "◎=1人気": F.ai1_pop == 1, "◎=2〜3人気": F.ai1_pop.between(2, 3), "◎=4人気以下": F.ai1_pop >= 4,
        "◎単勝3倍未満": F.ai1_odds < 3, "◎単勝3〜6倍": F.ai1_odds.between(3, 6), "◎単勝6倍以上": F.ai1_odds > 6,
        "◎が過小評価(AI/市場≧1.3)": F.ai1_ratio >= 1.3, "◎が過大人気(AI/市場<0.8)": F.ai1_ratio < 0.8,
        "AI上位3頭が全員5人気以内": F.ai_top3_in_pop5 == 3, "AI上位3頭に6人気以下あり": F.ai_top3_in_pop5 < 3,
        "1番人気2倍未満": F.fav_odds < 2, "1番人気3倍以上(混戦)": F.fav_odds >= 3,
        "〜9頭": F.field_size <= 9, "10〜11頭": F.field_size.between(10, 11), "12頭〜": F.field_size >= 12,
        "南関東": mk, "南関東以外": ~mk,
        "賞金 下位1/3": F.prize < q[0], "賞金 上位1/3": F.prize >= q[1],
        "1400m以下": F.distance <= 1400, "1500m以上": F.distance >= 1500,
    }


def evaluate(R, F, select_until):
    conds = conditions(F)
    names = list(conds)
    is_sel = pd.to_datetime(F.race_date) < select_until
    pn = R.pivot(index="race_id", columns="structure", values="n").reindex(F.index).fillna(0)
    pr = R.pivot(index="race_id", columns="structure", values="ret").reindex(F.index).fillna(0)
    rows = []
    for cond in [(x,) for x in names] + list(combinations(names[1:], 2)):
        mask = conds[cond[0]].copy()
        for x in cond[1:]:
            mask &= conds[x]
        mask = mask.fillna(False).astype(bool)
        for period, pm in [("選定", is_sel), ("検証", ~is_sel)]:
            m = (mask & pm).to_numpy()
            if m.sum() == 0:
                continue
            n, r = pn[m].sum(), pr[m].sum()
            for s in pn.columns:
                if n[s]:
                    rows.append(dict(cond=" & ".join(cond), structure=s, period=period, races=int(m.sum()),
                                     tickets=int(n[s]), roi=r[s] / (n[s] * 100)))
    res = pd.DataFrame(rows)
    wide = res.pivot_table(index=["cond", "structure"], columns="period", values=["roi", "races", "tickets"])
    wide.columns = [f"{x}_{y}" for x, y in wide.columns]
    return wide.reset_index()


def bootstrap_ci(R, F, cond_name, structure, period, select_until, n_boot=2000, seed=0, exclude_top=0):
    conds = conditions(F)
    mask = pd.Series(True, index=F.index)
    for x in cond_name.split(" & "):
        mask &= conds[x].fillna(False)
    is_sel = pd.to_datetime(F.race_date) < select_until
    mask &= is_sel if period == "選定" else ~is_sel
    sub = R[(R.structure == structure) & R.race_id.isin(F.index[mask])]
    if sub.empty:
        return np.nan, np.nan, np.nan
    n, ret = sub.n.to_numpy(), sub.ret.to_numpy().astype(float)
    trimmed = np.sort(ret)[: len(ret) - exclude_top].sum() / (n.sum() * 100) if exclude_top else np.nan
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(sub), (n_boot, len(sub)))
    bs = ret[idx].sum(1) / (n[idx].sum(1) * 100)
    return np.percentile(bs, 2.5), np.percentile(bs, 97.5), trimmed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("preds")
    ap.add_argument("payouts")
    ap.add_argument("--select-until", default="2026-01-01")
    ap.add_argument("--out", default="nar_strategy_search.csv")
    ap.add_argument("--min-races", type=int, default=300, help="選定期間でこのレース数以上の組み合わせだけ候補にする")
    a = ap.parse_args()
    preds = pd.read_parquet(a.preds)
    preds["race_id"] = preds["race_id"].astype(str)
    payouts = pd.read_csv(a.payouts, dtype={"race_id": str, "combo": str})
    payouts["payout"] = pd.to_numeric(payouts["payout"].astype(str).str.replace(",", ""), errors="coerce").fillna(0)
    preds = preds[preds.race_id.isin(set(payouts.race_id))]
    pay = payouts.groupby(["race_id", "bet_type", "combo"])["payout"].sum().to_dict()
    R, F = race_table(preds, pay)
    W = evaluate(R, F, a.select_until)
    W.to_csv(a.out, index=False)
    print(f"レース数 {len(F)}(選定 {int((pd.to_datetime(F.race_date) < a.select_until).sum())})/ 組み方×条件 {len(W)}")

    base = W[W.cond == "全レース"].sort_values("roi_選定", ascending=False)
    print("\n■ 条件なし(全レース)の組み方別 回収率")
    print(base[["structure", "races_選定", "roi_選定", "roi_検証"]].to_string(index=False, float_format="%.3f"))

    cand = W[(W.races_選定 >= a.min_races) & (W.roi_選定 >= 1.0)].sort_values("roi_選定", ascending=False)
    print(f"\n■ 選定期間で回収率100%以上(選定{a.min_races}R以上): {len(cand)}件。上位30件の検証結果")
    top = cand.head(30).copy()
    ci = [bootstrap_ci(R, F, r.cond, r.structure, "検証", a.select_until, exclude_top=5) for r in top.itertuples()]
    top["検証95%下限"], top["検証95%上限"], top["検証 上位5本除く"] = zip(*ci)
    print(top[["cond", "structure", "races_選定", "roi_選定", "races_検証", "roi_検証", "検証95%下限", "検証95%上限",
               "検証 上位5本除く"]].to_string(index=False, float_format="%.3f"))
    if len(cand):
        print(f"\n候補全体の検証回収率: 平均 {cand.roi_検証.mean():.3f} / 100%超の割合 {(cand.roi_検証 > 1).mean():.2f}"
              f"(選定で良かったものが検証でも良いか = 偶然でないかの目安)")


if __name__ == "__main__":
    main()
