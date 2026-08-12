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

    現状、netkeiba_parser.py は現在レースの静的項目(枠・馬番・性齢・斤量・
    通算成績・人気・脚質・休養週数)は安定して抽出できますが、直近5走の
    詳細(人気推移・着差推移・上がり3F推移・通過順推移)についてはまだ
    Python側の解析ロジックが未整備です(ブラウザ版ツールのJS実装が先行しています)。
    そのため、以下の直近5走系フィールドは現状 None(欠損)のまま渡しており、
    LightGBM側は欠損値を自動的に処理します(精度はやや下がりますが動作はします)。

    TODO: nar_fullpage_parser.js の parseDetailedPastRaces 相当のロジックを
    netkeiba形式向けに実装し、last_ninki 等を実値で埋める。
    """
    starts, winrate, top3rate = career_record_to_stats(horse.get('career_record'))

    # 「中N週」の休養情報を days_since_last の粗い近似として使う(1週=7日)
    weeks = horse.get('weeks_since_last')
    days_since_last = weeks * 7 if weeks is not None else None

    return {
        '枠_x': horse.get('waku'),
        '馬番': horse.get('umaban'),
        '齢': horse.get('rei'),
        '斤量': horse.get('kinryo'),
        'distance_main': race.get('distance'),
        '頭数_real': race.get('headcount'),
        'days_since_last': days_since_last,
        'last_ninki': None,      # TODO: 直近5走詳細パーサー実装後に接続
        'avg5_ninki': None,      # TODO
        'last_margin': None,     # TODO
        'avg5_margin': None,     # TODO
        'avg5_last3f': None,     # TODO
        'avg5_headcount': None,  # TODO
        'same_track_as_last': None,  # TODO
        'n_past_races': None,        # TODO
        'career_starts': starts,
        'career_winrate': winrate,
        'career_top3rate': top3rate,
        'avg5_corner_first': None,  # TODO
        'avg5_corner_last': None,   # TODO
        'avg5_corner_gain': None,   # TODO
        '場所': race.get('track'),
        '性': horse.get('sei'),
        'surface_main': race.get('surface'),
        'レースの格': race.get('grade'),
    }
