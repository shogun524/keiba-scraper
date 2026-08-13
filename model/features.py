"""
model_early_urawa_is_win.txt / model_early_urawa_is_top3.txt が期待する
特徴量セットの定義と、netkeiba形式の解析結果からの変換ロジック。

このモデルは「馬体重を使わない」設計です(検証の結果、精度への影響がほぼ無かったため)。
そのため、レース前日に出馬表が発表された時点で予想を実行できます。
"""

FEATURE_COLS_NUMERIC = [
    '枠_x', '馬番', '齢', '斤量', 'distance_main', '頭数_real',
    'days_since_last', 'last_ninki', 'avg5_ninki', 'last_margin', 'avg5_margin',
    'avg5_last3f', 'avg5_headcount', 'same_track_as_last', 'n_past_races',
    'career_starts', 'career_winrate', 'career_top3rate',
    'avg5_corner_first', 'avg5_corner_last', 'avg5_corner_gain',
]
FEATURE_COLS_CATEGORICAL = ['場所', '性', 'surface_main', 'レースの格']
ALL_FEATURES = FEATURE_COLS_NUMERIC + FEATURE_COLS_CATEGORICAL


def career_record_to_stats(record: str | None):
    """'1-0-0-0' 形式の通算成績を (starts, winrate, top3rate) に変換する。
    '初騎乗'(未出走)や None の場合は (0, None, None) を返す。
    """
    if not record or record == '初騎乗':
        return 0, None, None
    parts = record.split('-')
    if len(parts) != 4:
        return 0, None, None
    w, s2, s3, out = (int(p) for p in parts)
    total = w + s2 + s3 + out
    if total == 0:
        return 0, None, None
    return total, w / total, (w + s2 + s3) / total


def horse_to_feature_row(horse: dict, race: dict) -> dict:
    """netkeiba_parser.parse_race_card() の1頭分の出力(horse)と
    レース共通情報(race: track/distance/surface/grade/headcount)から
    モデル入力用の1行を作る。

    horse['recent_form'] に netkeiba_recent_form.build_recent_form_features() の
    出力(last_ninki, avg5_ninki, avg5_margin, avg5_last3f, avg5_corner_* 等)が
    入っていればそれを使い、無ければ欠損値(None)のまま渡す
    (LightGBM側が自動的に処理する)。
    """
    starts, winrate, top3rate = career_record_to_stats(horse.get('career_record'))

    weeks = horse.get('weeks_since_last')
    days_since_last = weeks * 7 if weeks is not None else None

    rf = horse.get('recent_form', {}) or {}

    same_track_as_last = None

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
        'career_starts': starts,
        'career_winrate': winrate,
        'career_top3rate': top3rate,
        'avg5_corner_first': rf.get('avg5_corner_first'),
        'avg5_corner_last': rf.get('avg5_corner_last'),
        'avg5_corner_gain': rf.get('avg5_corner_gain'),
        '場所': race.get('track'),
        '性': horse.get('sei'),
        'surface_main': race.get('surface'),
        'レースの格': race.get('grade'),
    }
