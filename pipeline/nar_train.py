"""
地方競馬AI v3 の学習・ウォークフォワード検証・本番モデルの保存。

1. 各年Y(--test-years)について「Y年より前だけで学習 → Y年を予測」し、未来を知らない予測を作る
2. その予測で、AI単体・市場(確定単勝オッズ)・両者の混合の精度(勝ち馬に付けた確率の対数損失)を比べ、
   混合の最適な重み(AI^a × 市場^b)を推定する。a>0 ならAIが市場に情報を足せている
3. ◎の単勝・複勝の回収率を、市場の1番人気と比べる
4. 全期間で学習し直したモデルを model/ に保存し、混合の重みを model/ev_calibration.json に書く

使い方:
    python pipeline/nar_train.py data/nar_features.parquet --payouts data/nar_payouts.csv --test-years 2024 2025 2026
"""
import argparse
import json
import os
import sys

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.optimize import minimize

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nar_features import CATEGORICAL, FEATURES  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARAMS = dict(objective="binary", learning_rate=0.05, num_leaves=63, min_data_in_leaf=200, feature_fraction=0.8,
              bagging_fraction=0.8, bagging_freq=1, lambda_l2=5, verbose=-1, seed=42)
ROUNDS = {"y_win": 300, "y_top3": 400}
TRAIN_FROM = "2023-01-01"  # 2022年は過去成績を貯めるための助走期間(特徴量が薄い)


def load(path):
    df = pd.read_parquet(path)
    df["race_date"] = pd.to_datetime(df["race_date"])
    for c in CATEGORICAL:
        df[c] = df[c].astype("category")
    return df


def fit(df, target, rounds):
    return lgb.train(PARAMS, lgb.Dataset(df[FEATURES], df[target], categorical_feature=CATEGORICAL), rounds)


def race_norm(d, col):
    return d[col] / d.groupby("race_id")[col].transform("sum")


def cond_logit(d, cols):
    """条件付きロジット(レース内で勝ち馬を当てる尤度)の係数と平均対数損失"""
    rid = pd.factorize(d["race_id"])[0]
    X = d[cols].to_numpy(float)
    win = d["y_win"].to_numpy() == 1

    def nll(th):
        s = X @ th
        n = rid.max() + 1
        mx = np.full(n, -np.inf)
        np.maximum.at(mx, rid, s)
        z = np.zeros(n)
        np.add.at(z, rid, np.exp(s - mx[rid]))
        return -(s[win] - mx[rid[win]] - np.log(z[rid[win]])).mean()
    x0 = np.zeros(len(cols))
    x0[-1] = 1.0
    r = minimize(nll, x0, method="BFGS")
    return r.x, float(r.fun), nll(np.eye(len(cols))[-1])


def evaluate(pred, payouts):
    d = pred[pred["odds"].notna() & (pred["odds"] > 0)].copy()
    ok = d.groupby("race_id").agg(w=("y_win", "sum"), n=("y_win", "size"))
    d = d[d["race_id"].isin(ok[(ok.w == 1) & (ok.n >= 5)].index)].copy()
    inv = 1 / d["odds"]
    d["p_mkt"] = inv / inv.groupby(d["race_id"]).transform("sum")
    d["l_ai"] = np.log(d["ai_win"].clip(1e-5))
    d["l_mkt"] = np.log(d["p_mkt"].clip(1e-5))
    w = d[d["y_win"] == 1]
    ll_ai = float(-w["l_ai"].mean())
    (a, b), ll_blend, ll_mkt = cond_logit(d, ["l_ai", "l_mkt"])
    hon = d[d["ai_rank"] == 1]
    fav = d[d["popularity"] == 1]
    res = dict(races=int(d["race_id"].nunique()), logloss_ai=round(ll_ai, 4), logloss_market=round(ll_mkt, 4),
               logloss_blend=round(ll_blend, 4), blend_a=round(float(a), 3), blend_b=round(float(b), 3),
               honmei_win=round(hon["y_win"].mean(), 3), fav_win=round(fav["y_win"].mean(), 3),
               honmei_is_fav=round((hon["popularity"] == 1).mean(), 3),
               honmei_tan_roi=round((hon["y_win"] * hon["odds"]).mean(), 3),
               fav_tan_roi=round((fav["y_win"] * fav["odds"]).mean(), 3))
    if payouts is not None:
        fk = payouts[payouts["bet_type"] == "複勝"].set_index(["race_id", "combo"])["payout"].to_dict()
        for name, sub in (("honmei", hon), ("fav", fav)):
            pay = [fk.get((r, str(int(u))), 0) for r, u in zip(sub["race_id"], sub["umaban"])]
            res[f"{name}_fuku_roi"] = round(np.mean(pay) / 100, 3)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("features")
    ap.add_argument("--payouts", default="")
    ap.add_argument("--test-years", nargs="+", type=int, default=[2024, 2025, 2026])
    ap.add_argument("--wf-out", default="data/nar_wf_preds.parquet")
    ap.add_argument("--no-final", action="store_true")
    a = ap.parse_args()
    df = load(a.features)
    payouts = pd.read_csv(a.payouts, dtype={"race_id": str, "combo": str}) if a.payouts and os.path.exists(a.payouts) else None
    df = df[df["race_date"] >= TRAIN_FROM]
    print(f"学習対象 {len(df):,}行 / {df['race_id'].nunique():,}レース")

    outs, summary = [], {}
    for Y in a.test_years:
        tr = df[df["race_date"] < f"{Y}-01-01"]
        te = df[(df["race_date"] >= f"{Y}-01-01") & (df["race_date"] < f"{Y + 1}-01-01")].copy()
        if te.empty or tr.empty:
            continue
        for tgt in ("y_win", "y_top3"):
            m = fit(tr, tgt, ROUNDS[tgt])
            te["p_" + tgt] = m.predict(te[FEATURES])
        te["ai_win"] = race_norm(te, "p_y_win")
        te["ai_top3"] = race_norm(te, "p_y_top3") * 3
        te["ai_rank"] = te.groupby("race_id")["p_y_win"].rank(ascending=False, method="first")
        r = evaluate(te, payouts)
        summary[str(Y)] = r
        print(f"\n[{Y}年] 学習{tr['race_id'].nunique():,}R → 予測{te['race_id'].nunique():,}R")
        print(json.dumps(r, ensure_ascii=False))
        outs.append(te)
    wf = pd.concat(outs, ignore_index=True)
    keep = ["race_id", "race_date", "track_code", "umaban", "horse", "finish", "y_win", "y_top3", "popularity", "odds",
            "ai_win", "ai_top3", "ai_rank", "field_size", "log_prize1", "distance", "is_graded"]
    os.makedirs(os.path.dirname(a.wf_out) or ".", exist_ok=True)
    wf[keep].to_parquet(a.wf_out)
    allr = evaluate(wf, payouts)
    summary["全期間"] = allr
    print("\n[検証期間 全体]", json.dumps(allr, ensure_ascii=False))
    pd.Series(fit(df, "y_win", ROUNDS["y_win"]).feature_importance("gain"), index=FEATURES).sort_values(ascending=False).head(15).pipe(print)

    if not a.no_final:
        mdir = os.path.join(ROOT, "model")
        for tgt in ("y_win", "y_top3"):
            m = fit(df, tgt, ROUNDS[tgt])
            m.save_model(os.path.join(mdir, f"model_nar_v3_{tgt[2:]}.txt"))
        cal = {"a": allr["blend_a"], "b": allr["blend_b"], "c_move": 0.0, "g2": 0.838, "g3": 0.713,
               "source": f"v3 ウォークフォワード {allr['races']}レース(確定オッズ)",
               "logloss_market": allr["logloss_market"], "logloss_blend": allr["logloss_blend"]}
        json.dump(cal, open(os.path.join(mdir, "ev_calibration.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        json.dump(summary, open(os.path.join(mdir, "v3_backtest.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        json.dump({"features": FEATURES, "categorical": CATEGORICAL, "data_last_date": str(df["race_date"].max().date())},
                  open(os.path.join(mdir, "v3_features.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print("本番モデルを保存しました: model/model_nar_v3_win.txt, model_nar_v3_top3.txt")


if __name__ == "__main__":
    main()
