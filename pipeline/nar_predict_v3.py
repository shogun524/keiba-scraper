"""
地方競馬AI v3 の予測(model/predict.py から呼ぶ)。

今日の出走馬(出馬表 shutuba_past のテキスト)を「まだ着順のない行」として過去の結果(nar_results.csv)に足し、
学習と同じ特徴量作成(nar_features.build)を通して、v3モデルで1着率・3着内率を出す。
オッズ・人気は使わない(AIの実力評価)。市場との混合はEVボード側(ev_board, ev_calibration.json)で行う。

v3モデルまたは過去の結果ファイルが無い場合は None を返し、predict.py は旧モデルを使う。
"""
import os
import re
import sys
import tempfile

import duckdb
import lightgbm as lgb
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "scraper"))
from nar_features import CATEGORICAL, FEATURES, build  # noqa: E402
from shutuba_past_parser import parse_race_card  # noqa: E402

MODEL_WIN = os.path.join(ROOT, "model", "model_nar_v3_win.txt")
MODEL_TOP3 = os.path.join(ROOT, "model", "model_nar_v3_top3.txt")
DEFAULT_RESULTS = os.path.join(ROOT, "data", "nar_results.csv")


def available(results_csv: str = DEFAULT_RESULTS) -> bool:
    return os.path.exists(MODEL_WIN) and os.path.exists(MODEL_TOP3) and os.path.exists(results_csv)


def _meta(raw: str) -> dict:
    m = {}
    x = re.search(r"(ダ|芝)(\d+)m", raw)
    if x:
        m["surface"] = "ダート" if x.group(1) == "ダ" else "芝"
        m["distance"] = int(x.group(2))
    x = re.search(r"馬場:(\S+?)(?:\s|$)", raw)
    if x:
        b = x.group(1)
        m["baba"] = {"不": "不良", "稍": "稍重"}.get(b, b)
    x = re.search(r"本賞金:([\d.]+)", raw)
    m["prize1"] = float(x.group(1)) if x else None
    x = re.search(r"(\d+)頭", raw)
    m["head_count"] = int(x.group(1)) if x else None
    m["is_graded"] = int(bool(re.search(r"重賞|Jpn|JPN", raw[:3000])))
    return m


def entry_rows(records: list[dict]) -> pd.DataFrame:
    rows = []
    for rec in records:
        rid, raw = rec["race_id"], rec["raw_text"]
        meta = _meta(raw)
        for h in parse_race_card(raw):
            if not h.get("name"):
                continue
            rows.append({
                "race_id": rid, "race_date": rec["date"], "track_code": rid[4:6], "race_no": int(rid[-2:]),
                "surface": meta.get("surface"), "distance": meta.get("distance"), "baba": meta.get("baba"),
                "head_count": meta.get("head_count"), "prize1": meta.get("prize1"), "is_graded": meta.get("is_graded"),
                "finish": None, "waku": h.get("waku"), "umaban": h.get("umaban"), "horse": h.get("name"),
                "sex": h.get("sei"), "age": h.get("rei"), "weight_carry": h.get("kinryo"), "jockey": h.get("jockey"),
                "trainer": h.get("trainer"), "odds": h.get("odds"), "popularity": h.get("ninki"), "is_entry": "1",
            })
    return pd.DataFrame(rows)


def predict(records: list[dict], results_csv: str = DEFAULT_RESULTS):
    """戻り値: {race_id: DataFrame(umaban, p_ai_win, p_ai_top3)}。使えなければ None"""
    if not available(results_csv) or not records:
        return None
    ent = entry_rows(records)
    if ent.empty:
        return None
    hist = pd.read_csv(results_csv, dtype=str)
    hist = hist[hist["race_date"] < ent["race_date"].min()]  # 予測日より前の結果だけ(リーク防止)
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "combined.csv")
        pd.concat([hist, ent.astype(str).replace({"None": None, "nan": None})], ignore_index=True).to_csv(path, index=False)
        con = duckdb.connect()
        build(con, path)
        f = con.execute("SELECT * FROM features WHERE is_entry").df()
    if f.empty:
        return None
    for c in CATEGORICAL:
        f[c] = f[c].astype("category")
    mw, mt = lgb.Booster(model_file=MODEL_WIN), lgb.Booster(model_file=MODEL_TOP3)
    f["pw"] = mw.predict(f[FEATURES])
    f["pt"] = mt.predict(f[FEATURES])
    out = {}
    for rid, g in f.groupby("race_id"):
        g = g.copy()
        g["p_ai_win"] = g["pw"] / g["pw"].sum()
        g["p_ai_top3"] = np.clip(g["pt"] / g["pt"].sum() * min(3, len(g)), 0, 1)
        out[str(rid)] = g[["umaban", "p_ai_win", "p_ai_top3", "h_starts"]]
    return out
