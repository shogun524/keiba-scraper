"""
スクレイピング済み出馬表(scraper_netkeiba.py の出力 .jsonl)を読み込み、
実際にモデルでスコアリングして予想結果CSVを出力する。

使い方:
    python predict.py --input scraped_data/2026-08-14_racecards_raw.jsonl
"""
import sys
import json
from pathlib import Path

import pandas as pd
import lightgbm as lgb

sys.path.insert(0, str(Path(__file__).parent.parent / "scraper"))
from netkeiba_parser import parse_race_card  # noqa: E402
from features import ALL_FEATURES, FEATURE_COLS_CATEGORICAL, horse_to_feature_row  # noqa: E402

MODEL_DIR = Path(__file__).parent


def load_models():
    win_model = lgb.Booster(model_file=str(MODEL_DIR / "model_early_urawa_is_win.txt"))
    top3_model = lgb.Booster(model_file=str(MODEL_DIR / "model_early_urawa_is_top3.txt"))
    return win_model, top3_model


def guess_race_meta(raw_text: str, track: str) -> dict:
    """レース共通情報(距離・コース種別・クラス・頭数)を推測する。
    netkeiba_parser.py はまだレースヘッダー自体の解析に対応していないため、
    ここでは簡易的な正規表現で拾う(要改善)。
    """
    import re
    meta = {"track": track, "surface": "ダ", "distance": None, "grade": "未格付", "headcount": None}
    m = re.search(r'ダ(\d+)', raw_text)
    if m:
        meta["distance"] = float(m.group(1))
    m = re.search(r'\((C[123]|B[123]|A[123]|OP|新馬|Jpn[123]|重賞)\)', raw_text)
    if m:
        meta["grade"] = m.group(1)
    return meta


def predict_race(race_id: str, track: str, raw_text: str, win_model, top3_model) -> pd.DataFrame:
    horses = parse_race_card(raw_text)
    if not horses:
        return pd.DataFrame()

    race_meta = guess_race_meta(raw_text, track)
    race_meta["headcount"] = len(horses)

    rows = [horse_to_feature_row(h, race_meta) for h in horses]
    df = pd.DataFrame(rows)
    for c in FEATURE_COLS_CATEGORICAL:
        df[c] = df[c].astype('category')
    for c in [f for f in ALL_FEATURES if f not in FEATURE_COLS_CATEGORICAL]:
        # 値が全てNoneの列はobject型になりLightGBMが受け付けないため、明示的にfloat化する
        df[c] = pd.to_numeric(df[c], errors='coerce')

    df['p_win_raw'] = win_model.predict(df[ALL_FEATURES])
    df['p_top3_raw'] = top3_model.predict(df[ALL_FEATURES])
    # レース内で単勝確率を正規化(合計1になるように)
    df['p_win'] = df['p_win_raw'] / df['p_win_raw'].sum()
    df['p_top3'] = df['p_top3_raw']

    df['horse_name'] = [h.get('name') for h in horses]
    df['race_id'] = race_id
    df = df.sort_values('p_win', ascending=False).reset_index(drop=True)
    df['rank'] = df.index + 1

    return df[['rank', 'race_id', '馬番', 'horse_name', 'p_win', 'p_top3']]


def main(input_path: str):
    win_model, top3_model = load_models()

    results = []
    with open(input_path, encoding='utf-8') as f:
        for line in f:
            if not line.strip():
                continue
            record = json.loads(line)
            pred = predict_race(record['race_id'], record['track'], record['raw_text'],
                                 win_model, top3_model)
            if not pred.empty:
                pred['date'] = record['date']
                pred['track'] = record['track']
                pred['race_num'] = record['race_num']
                results.append(pred)

    if not results:
        print('予想できたレースがありませんでした。')
        return

    all_pred = pd.concat(results, ignore_index=True)
    out_path = Path(input_path).with_name(Path(input_path).stem + '_predictions.csv')
    all_pred.to_csv(out_path, index=False, encoding='utf-8-sig')
    print(f'保存: {out_path} ({len(results)}レース分)')

    # 各レースのAI1位だけ簡易表示
    for pred in results:
        top = pred.iloc[0]
        print(f"{top['race_id']}: 1位予想 {top['馬番']}番 {top['horse_name']} "
              f"(単勝{top['p_win']*100:.1f}% / 複勝{top['p_top3']*100:.1f}%)")


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='スクレイピング済みデータから予想を実行')
    parser.add_argument('--input', required=True, help='scraper_netkeiba.py の出力(.jsonl)パス')
    args, _unknown = parser.parse_known_args()

    main(args.input)
