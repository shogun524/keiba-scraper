"""
地方競馬の「込%」(オッズ込みの1着率)モデル。JRA の src/market_model.py と同じ考え方:

    勝つ確率 ∝ exp( β·log(1/単勝オッズ) + Σ w_k·要素_k )   (レースごとに合計1)

単勝オッズから見た勝つ確率を土台に、市場が織り込み切れていない要素(nar_features の過去の成績など)だけを足す条件付きロジット。
β_market はオッズだけのモデルの β(「オッズから見た確率」= 妙味の比べる相手)。

使い方:
  python pipeline/nar_market_model.py fit data/nar_features.parquet model/nar_market_model.json
  from nar_market_model import apply_probs; p, pm = apply_probs(df, spec)
"""
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nar_features import CATEGORICAL, FEATURES  # noqa: E402

FEATS = [f for f in FEATURES if f not in CATEGORICAL and f not in ("race_no", "is_graded")]
MODEL_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "model", "nar_market_model.json")


def _design(df, spec, odds_col):
    cols = [np.log(1 / df[odds_col].astype(float).values)]
    for f in spec["feats"]:
        x = pd.to_numeric(df[f], errors="coerce").astype(float).values if f in df.columns else np.full(len(df), np.nan)
        z = np.clip(np.where(np.isnan(x), 0, (x - spec["mu"][f]) / spec["sd"][f]), -4, 4)
        cols += [z, np.isnan(x).astype(float)]
    return np.column_stack(cols)


def _fit_logit(X, gid, y):
    from scipy.optimize import minimize
    starts = np.r_[0, np.flatnonzero(gid[1:] != gid[:-1]) + 1]
    idx = np.repeat(np.arange(len(starts)), np.diff(np.r_[starts, len(gid)]))

    def f(w):
        s = X @ w
        m = np.maximum.reduceat(s, starts)
        e = np.exp(s - m[idx])
        Z = np.add.reduceat(e, starts)
        p = e / Z[idx]
        return -(y * (s - m[idx] - np.log(Z[idx]))).sum() / len(starts), -((y - p)[:, None] * X).sum(0) / len(starts)
    w0 = np.zeros(X.shape[1]); w0[0] = 1.0
    return minimize(f, w0, jac=True, method="L-BFGS-B").x


def _softmax(s, gid):
    s = pd.Series(s, index=gid.index)
    e = np.exp(s - s.groupby(gid).transform("max"))
    return (e / e.groupby(gid).transform("sum")).values


def apply_probs(df, spec, odds_col="odds"):
    """-> (込%, オッズから見た確率)。df は1レース以上(race_id 列でまとまり)"""
    rid = df["race_id"].astype(str)
    p = _softmax(_design(df, spec, odds_col) @ np.asarray(spec["w"]), rid)
    pm = _softmax(spec["beta_market"] * np.log(1 / df[odds_col].astype(float).values), rid)
    return p, pm


def _prep(path):
    F = pd.read_parquet(path)
    F["race_date"] = pd.to_datetime(F["race_date"])
    F["odds"] = pd.to_numeric(F["odds"], errors="coerce")
    F = F[(F["race_date"] >= "2023-01-01") & F["odds"].gt(1.0 - 1e-9) & F["finish"].notna() & (F["is_entry"] != True)]  # noqa: E712
    F["y"] = (pd.to_numeric(F["finish"], errors="coerce") == 1).astype(float)
    F = F[F.groupby("race_id")["y"].transform("sum") == 1]
    F = F[F.groupby("race_id")["odds"].transform("count") == F.groupby("race_id")["umaban"].transform("size")]
    return F.sort_values(["race_id", "umaban"]).reset_index(drop=True)


def fit(path, out, test_from="2025-01-01"):
    F = _prep(path)

    def spec_of(d):
        mu = {f: float(np.nanmean(pd.to_numeric(d[f], errors="coerce"))) for f in FEATS}
        sd = {f: float(np.nanstd(pd.to_numeric(d[f], errors="coerce")) or 1.0) for f in FEATS}
        return dict(feats=FEATS, mu=mu, sd=sd)
    report = {}
    tr, te = F[F.race_date < test_from], F[F.race_date >= test_from].copy()
    sp = spec_of(tr)
    sp["w"] = _fit_logit(_design(tr, sp, "odds"), tr["race_id"].values, tr["y"].values).tolist()
    sp["beta_market"] = float(_fit_logit(np.log(1 / tr["odds"].values)[:, None], tr["race_id"].values, tr["y"].values)[0])
    te["p"], te["pm"] = apply_probs(te, sp)
    n = te.race_id.nunique()
    ll = lambda c: float(-np.log(te.loc[te.y == 1, c]).sum() / n)  # noqa: E731
    top = te.loc[te.groupby("race_id")["p"].idxmax()]
    fav = te.loc[te.groupby("race_id")["odds"].idxmin()]
    val = te[te.p / te.pm >= 1.15]
    report = dict(test_from=test_from, races=n, logloss_model=round(ll("p"), 4), logloss_market=round(ll("pm"), 4),
                  top_win=round(top.y.mean(), 3), top_roi=round((top.y * top.odds).mean() * 100, 1),
                  fav_win=round(fav.y.mean(), 3), fav_roi=round((fav.y * fav.odds).mean() * 100, 1),
                  value_n=int(len(val)), value_roi=round((val.y * val.odds).mean() * 100, 1),
                  all_roi=round((te.y * te.odds).mean() * 100, 1))
    print("[確認]", report)
    te[["race_id", "race_date", "umaban", "odds", "popularity", "finish", "y", "p", "pm"]].to_parquet(out.replace(".json", "_test.parquet"))
    sp = spec_of(F)
    sp["w"] = _fit_logit(_design(F, sp, "odds"), F["race_id"].values, F["y"].values).tolist()
    sp["beta_market"] = float(_fit_logit(np.log(1 / F["odds"].values)[:, None], F["race_id"].values, F["y"].values)[0])
    sp["report"] = report
    sp["trained_until"] = str(F.race_date.max().date())
    with open(out, "w", encoding="utf-8") as f:
        json.dump(sp, f, ensure_ascii=False, indent=1)
    print(f"[INFO] {out} に保存")


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "fit":
        fit(sys.argv[2], sys.argv[3])
    else:
        print(__doc__)
