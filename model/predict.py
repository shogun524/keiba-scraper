"""
スクレイピング済み出馬表(scraper_netkeiba.py の出力 .jsonl)を読み込み、
実際にモデルでスコアリングして予想結果CSVを出力する。

shutuba_past.html 形式(プレミアム制限なし・全頭直近5走詳細取得可)に対応。

使い方:
    python predict.py --input scraped_data/2026-08-14_racecards_raw.jsonl
"""
import sys
import json
import re
from pathlib import Path

import pandas as pd
import lightgbm as lgb

sys.path.insert(0, str(Path(__file__).parent.parent / "scraper"))
from shutuba_past_parser import parse_race_card  # noqa: E402

MODEL_DIR = Path(__file__).parent

FEATURE_COLS_NUMERIC = [
    '枠_x', '馬番', '齢', '斤量', 'distance_main', '頭数_real',
    'days_since_last', 'last_ninki', 'avg5_ninki', 'last_margin', 'avg5_margin',
    'avg5_last3f', 'avg5_headcount', 'same_track_as_last', 'n_past_races',
    'career_starts', 'career_winrate', 'career_top3rate',
    'avg5_corner_first', 'avg5_corner_last', 'avg5_corner_gain',
]
FEATURE_COLS_CATEGORICAL = ['場所', '性', 'surface_main', 'レースの格']
ALL_FEATURES = FEATURE_COLS_NUMERIC + FEATURE_COLS_CATEGORICAL


def load_models():
    win_model = lgb.Booster(model_file=str(MODEL_DIR / "model_early_urawa_is_win.txt"))
    top3_model = lgb.Booster(model_file=str(MODEL_DIR / "model_early_urawa_is_top3.txt"))
    return win_model, top3_model


def guess_race_meta(raw_text: str, track: str) -> dict:
    """レース共通情報(距離・コース種別・クラス・頭数)を推測する。"""
    meta = {"track": track, "surface": "ダ", "distance": None, "grade": "未格付", "headcount": None}
    m = re.search(r'(ダ|芝)(\d+)m', raw_text)
    if m:
        meta["surface"] = m.group(1)
        meta["distance"] = float(m.group(2))
    m = re.search(r'サラ系\S*\s+(新馬|OP|Jpn[123]|重賞|[ABC][123])', raw_text)
    if m:
        meta["grade"] = m.group(1)
    return meta


def horse_to_feature_row(horse: dict, race: dict) -> dict:
    rf = horse.get('recent_form', {}) or {}
    weeks = horse.get('weeks_since_last')
    days_since_last = weeks * 7 if weeks is not None else None
    same_track_as_last = None
    if rf.get('most_recent_track') and race.get('track'):
        same_track_as_last = int(rf['most_recent_track'] == race['track'])

    return {
        '枠_x': horse.get('waku'),
        '馬番': horse.get('umaban'),
        '齢': horse.get('rei'),
        '斤量': horse.get('kinryo'),
        'distance_main': race.get('distance'),
        '頭数_real': race.get('headcount'),
        'days_since_last': days_since_last,
        'last_ninki': rf.get('last_ninki'),
        'avg5_ninki': rf.get('avg5_ninki'),
        'last_margin': rf.get('last_margin'),
        'avg5_margin': rf.get('avg5_margin'),
        'avg5_last3f': rf.get('avg5_last3f'),
        'avg5_headcount': rf.get('avg5_headcount'),
        'same_track_as_last': same_track_as_last,
        'n_past_races': rf.get('n_past_races'),
        'career_starts': None,
        'career_winrate': None,
        'career_top3rate': None,
        'avg5_corner_first': rf.get('avg5_corner_first'),
        'avg5_corner_last': rf.get('avg5_corner_last'),
        'avg5_corner_gain': rf.get('avg5_corner_gain'),
        '場所': race.get('track'),
        '性': horse.get('sei'),
        'surface_main': race.get('surface'),
        'レースの格': race.get('grade'),
    }


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
        df[c] = pd.to_numeric(df[c], errors='coerce')

    df['p_win_raw'] = win_model.predict(df[ALL_FEATURES])
    df['p_top3_raw'] = top3_model.predict(df[ALL_FEATURES])
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
