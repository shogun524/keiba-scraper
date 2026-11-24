"""
地方競馬AI v3 の特徴量作成(nar_results.csv -> nar_features.parquet)。

旧モデル(model_nar11v2)は「人気」「オッズの確率」を特徴量に入れていたため、予想がほぼオッズの写し
(◎が1番人気の割合が約98%)になり、市場を上回る情報を持てなかった。v3 はオッズ・人気を一切使わず、
過去の結果だけから「そのレースより前に分かっていたこと」で特徴量を作る(リーク防止)。

- 馬    : 通算・直近5走の着順率/3着内率、勝ち馬とのタイム差、上がり順位、4角位置(脚質)、タイム指数、
          距離適性・コース適性、前走からの日数、クラス(1着賞金)の上げ下げ、前走の着順・人気
- 騎手  : 過去365日の勝率・3着内率・騎乗数(前日まで。当日の前のレースは使わない=朝の予想と同じ条件)
- 調教師: 同上
- レース: 距離・競馬場・馬場・頭数・1着賞金・枠・馬番・斤量・馬体重・増減・性齢

使い方:
    python pipeline/nar_features.py data/nar_results.csv data/nar_features.parquet
"""
import sys

import duckdb
import pandas as pd

# 騎手・調教師名の照合キー(結果ページはフルネーム、出馬表は短縮名のことがあるため、記号と所属を除いて先頭3文字)
AFFIL = "^(北海道|道営|岩手|水沢|盛岡|浦和|船橋|大井|川崎|金沢|笠松|愛知|名古屋|兵庫|園田|姫路|高知|佐賀|門別|美浦|栗東|JRA|地方|\\(|（)+・?"
JOCKEY_KEY = "left(regexp_replace(coalesce({c}, ''), '[▲△☆★◇.．・ 　]', '', 'g'), 3)"
TRAINER_KEY = "left(regexp_replace(regexp_replace(coalesce({c}, ''), '" + AFFIL + "', ''), '[・ 　()（）]', '', 'g'), 3)"
STD_UNTIL = "2023-01-01"  # タイム指数の基準タイムはこの日より前のデータだけで作る(評価期間へのリーク防止)


# 列の値にカンマを含むレース名があるので、引用符を明示する(自動判定だと失敗する)
CSV_OPTS = "all_varchar=true, header=true, delim=',', quote='\"', escape='\"'"


def build(con, results_csv: str):
    """results_csv に is_entry 列(1=これから走る今日の出走馬)があれば、その馬も同じ式で特徴量を作る
    (学習と予測で計算方法を完全に一致させるため)"""
    cols = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_csv('{results_csv}', {CSV_OPTS})").fetchall()]
    entry = "coalesce(is_entry, '0')" if "is_entry" in cols else "'0'"
    con.execute(f"""
    CREATE OR REPLACE TABLE raw AS
    SELECT * FROM (
        SELECT *, {entry} AS entry_flag,
               row_number() OVER (PARTITION BY race_id, umaban ORDER BY {entry} DESC, race_date) AS rn
        FROM read_csv('{results_csv}', {CSV_OPTS})
    ) WHERE rn = 1 AND race_date IS NOT NULL AND umaban IS NOT NULL
    """)
    con.execute(f"""
    CREATE OR REPLACE TABLE base AS
    SELECT
        race_id, CAST(race_date AS DATE) AS race_date, track_code, (entry_flag = '1') AS is_entry, surface, TRY_CAST(distance AS INT) AS distance,
        baba, TRY_CAST(head_count AS INT) AS head_count_page, TRY_CAST(prize1 AS DOUBLE) AS prize1,
        TRY_CAST(is_graded AS INT) AS is_graded, TRY_CAST(race_no AS INT) AS race_no,
        TRY_CAST(finish AS INT) AS finish, TRY_CAST(waku AS INT) AS waku, TRY_CAST(umaban AS INT) AS umaban,
        horse, sex, TRY_CAST(age AS INT) AS age, TRY_CAST(weight_carry AS DOUBLE) AS weight_carry,
        jockey, trainer,
        {JOCKEY_KEY.format(c='jockey')} AS jockey_key, {TRAINER_KEY.format(c='trainer')} AS trainer_key,
        TRY_CAST(popularity AS INT) AS popularity, TRY_CAST(odds AS DOUBLE) AS odds,
        TRY_CAST(last3f AS DOUBLE) AS last3f, TRY_CAST(horse_weight AS INT) AS horse_weight,
        TRY_CAST(weight_diff AS INT) AS weight_diff, TRY_CAST(c4 AS INT) AS c4,
        CASE WHEN regexp_matches(time, '^\\d+:\\d+(\\.\\d+)?$')
             THEN TRY_CAST(split_part(time, ':', 1) AS DOUBLE) * 60 + TRY_CAST(split_part(time, ':', 2) AS DOUBLE)
             WHEN regexp_matches(time, '^\\d+(\\.\\d+)?$') THEN TRY_CAST(time AS DOUBLE) END AS time_sec
    FROM raw
    """)
    # 出走頭数(取消・除外を除く)、着順率、勝ち馬とのタイム差、上がり順位率、4角位置率
    con.execute("""
    CREATE OR REPLACE TABLE r1 AS
    SELECT *,
        count(*) FILTER (WHERE finish IS NOT NULL OR odds IS NOT NULL OR is_entry) OVER w AS field_size,
        (finish IS NOT NULL AND finish = 1)::INT AS y_win,
        (finish IS NOT NULL AND finish <= 3)::INT AS y_top3,
        CASE WHEN distance < 1200 THEN 'S' WHEN distance < 1500 THEN 'M' WHEN distance < 1900 THEN 'I' ELSE 'L' END AS dist_bucket,
        CASE WHEN baba IN ('良') THEN '良' WHEN baba IN ('稍重', '稍') THEN '稍' ELSE '重不' END AS baba_grp
    FROM base
    WINDOW w AS (PARTITION BY race_id)
    """)
    con.execute("""
    CREATE OR REPLACE TABLE r2 AS
    SELECT *,
        finish::DOUBLE / NULLIF(field_size, 0) AS finish_ratio,
        time_sec - min(time_sec) OVER (PARTITION BY race_id) AS margin_sec,
        (rank() OVER (PARTITION BY race_id ORDER BY last3f) - 1)::DOUBLE / NULLIF(field_size - 1, 0) AS l3f_rank_ratio,
        (c4 - 1)::DOUBLE / NULLIF(field_size - 1, 0) AS c4_ratio
    FROM r1
    """)
    # タイム指数: (基準タイム - 走破タイム) / 距離 × 1000。基準 = 2023年より前の 場×距離×馬場 の平均(1着馬)
    con.execute(f"""
    CREATE OR REPLACE TABLE std AS
    SELECT track_code, distance, baba_grp, avg(time_sec) AS std_time, count(*) AS n
    FROM r2 WHERE finish = 1 AND time_sec IS NOT NULL AND race_date < DATE '{STD_UNTIL}'
    GROUP BY 1, 2, 3 HAVING count(*) >= 5
    """)
    con.execute("""
    CREATE OR REPLACE TABLE r3 AS
    SELECT r.*, (s.std_time - r.time_sec) / NULLIF(r.distance, 0) * 1000 AS time_index
    FROM r2 r LEFT JOIN std s USING (track_code, distance, baba_grp)
    """)
    # 馬の過去成績(そのレースより前だけ)
    con.execute("""
    CREATE OR REPLACE TABLE horse_f AS
    SELECT race_id, umaban,
        count(*) OVER hp AS h_starts,
        avg(y_win) OVER hp AS h_win_rate,
        avg(y_top3) OVER hp AS h_top3_rate,
        avg(finish_ratio) OVER h5 AS h5_finish_ratio,
        avg(y_top3) OVER h5 AS h5_top3_rate,
        avg(margin_sec) OVER h5 AS h5_margin,
        avg(l3f_rank_ratio) OVER h5 AS h5_l3f_rank,
        avg(c4_ratio) OVER h5 AS h5_c4_ratio,
        avg(time_index) OVER h5 AS h5_time_index,
        max(time_index) OVER h5 AS h5_best_time_index,
        avg(popularity) OVER h5 AS h5_popularity,
        lag(finish_ratio) OVER h AS last_finish_ratio,
        lag(margin_sec) OVER h AS last_margin,
        lag(popularity) OVER h AS last_popularity,
        lag(time_index) OVER h AS last_time_index,
        date_diff('day', lag(race_date) OVER h, race_date) AS days_since_last,
        distance - lag(distance) OVER h AS dist_change,
        (track_code = lag(track_code) OVER h)::INT AS same_track_as_last,
        ln(NULLIF(prize1, 0) / NULLIF(lag(prize1) OVER h, 0)) AS class_change,
        ln(NULLIF(prize1, 0) / NULLIF(avg(prize1) OVER h5, 0)) AS class_vs_avg5,
        weight_carry - lag(weight_carry) OVER h AS carry_change
    FROM r3
    WINDOW h AS (PARTITION BY horse ORDER BY race_date, race_id),
           hp AS (PARTITION BY horse ORDER BY race_date, race_id ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING),
           h5 AS (PARTITION BY horse ORDER BY race_date, race_id ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING)
    """)
    # 距離帯・競馬場ごとの適性(そのレースより前)
    con.execute("""
    CREATE OR REPLACE TABLE apt_f AS
    SELECT race_id, umaban,
        count(*) OVER d AS dist_starts, avg(y_top3) OVER d AS dist_top3_rate, avg(time_index) OVER d AS dist_time_index,
        count(*) OVER t AS track_starts, avg(y_top3) OVER t AS track_top3_rate
    FROM r3
    WINDOW d AS (PARTITION BY horse, dist_bucket ORDER BY race_date, race_id ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING),
           t AS (PARTITION BY horse, track_code ORDER BY race_date, race_id ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING)
    """)
    # 騎手・調教師: 日ごとに集計してから「前日までの365日」で合計(当日の前のレースは使わない)
    for who in ("jockey", "trainer"):
        con.execute(f"""
        CREATE OR REPLACE TABLE {who}_day AS
        SELECT {who}_key AS k, race_date, count(finish) AS rides,
            sum(CASE WHEN finish IS NOT NULL THEN y_win END) AS wins, sum(CASE WHEN finish IS NOT NULL THEN y_top3 END) AS top3
        FROM r3 WHERE {who}_key <> '' GROUP BY 1, 2   -- 出走予定の日(着順なし)も行を作る: 予測時に「前日までの365日」を結合できるように
        """)
        con.execute(f"""
        CREATE OR REPLACE TABLE {who}_roll AS
        SELECT k, race_date,
            sum(rides) OVER w AS r365, sum(wins) OVER w AS w365, sum(top3) OVER w AS t365
        FROM {who}_day
        WINDOW w AS (PARTITION BY k ORDER BY race_date RANGE BETWEEN INTERVAL 365 DAYS PRECEDING AND INTERVAL 1 DAYS PRECEDING)
        """)
    con.execute("""
    CREATE OR REPLACE TABLE features AS
    SELECT r.race_id, r.race_date, r.track_code, r.surface, r.distance, r.baba_grp, r.dist_bucket, r.field_size,
        ln(NULLIF(r.prize1, 0)) AS log_prize1, r.is_graded, r.race_no, r.waku, r.umaban, r.sex, r.age, r.weight_carry,
        r.horse_weight, r.weight_diff, r.horse, r.jockey_key, r.trainer_key,
        r.finish, r.y_win, r.y_top3, r.popularity, r.odds, r.is_entry,
        r.umaban::DOUBLE / NULLIF(r.field_size, 0) AS umaban_ratio,
        h.* EXCLUDE (race_id, umaban), a.* EXCLUDE (race_id, umaban),
        j.r365 AS jockey_rides, j.w365::DOUBLE / NULLIF(j.r365, 0) AS jockey_win_rate,
        j.t365::DOUBLE / NULLIF(j.r365, 0) AS jockey_top3_rate,
        t.r365 AS trainer_runs, t.w365::DOUBLE / NULLIF(t.r365, 0) AS trainer_win_rate,
        t.t365::DOUBLE / NULLIF(t.r365, 0) AS trainer_top3_rate
    FROM r3 r
    JOIN horse_f h USING (race_id, umaban)
    JOIN apt_f a USING (race_id, umaban)
    LEFT JOIN jockey_roll j ON j.k = r.jockey_key AND j.race_date = r.race_date
    LEFT JOIN trainer_roll t ON t.k = r.trainer_key AND t.race_date = r.race_date
    WHERE r.finish IS NOT NULL OR r.odds IS NOT NULL OR r.is_entry
    """)


NUMERIC = [
    "distance", "field_size", "log_prize1", "is_graded", "race_no", "waku", "umaban", "umaban_ratio", "age",
    "weight_carry", "horse_weight", "weight_diff",
    "h_starts", "h_win_rate", "h_top3_rate", "h5_finish_ratio", "h5_top3_rate", "h5_margin", "h5_l3f_rank",
    "h5_c4_ratio", "h5_time_index", "h5_best_time_index", "h5_popularity", "last_finish_ratio", "last_margin",
    "last_popularity", "last_time_index", "days_since_last", "dist_change", "same_track_as_last", "class_change",
    "class_vs_avg5", "carry_change", "dist_starts", "dist_top3_rate", "dist_time_index", "track_starts",
    "track_top3_rate", "jockey_rides", "jockey_win_rate", "jockey_top3_rate", "trainer_runs", "trainer_win_rate",
    "trainer_top3_rate",
]
CATEGORICAL = ["track_code", "surface", "baba_grp", "dist_bucket", "sex"]

# ---- JRAのAIと同じ作りの特徴量(11/24): レース内の比較・騎手×調教師・枠の有利不利・展開
# ウォークフォワード(その年より前だけで学習)で、◎の勝率 2024 37.4→38.1% / 2025 38.3→38.9% / 2026 39.8→40.6%、
# 勝ち馬に付けた確率の対数損失も3年とも改善(1.734→1.728 / 1.724→1.711 / 1.693→1.673)
REL_BASE = ["h5_time_index", "h5_best_time_index", "last_time_index", "dist_time_index", "h5_c4_ratio", "h5_l3f_rank",
            "h5_finish_ratio", "h_top3_rate", "jockey_win_rate", "trainer_win_rate", "track_top3_rate", "h5_popularity",
            "last_popularity", "h5_margin", "weight_carry", "age"]
REL_ASC = {"h5_c4_ratio", "h5_l3f_rank", "h5_finish_ratio", "h5_popularity", "last_popularity", "h5_margin"}
EXTRA = [c + s for c in REL_BASE for s in ("_rk", "_d")] + ["n_front", "jt_n", "jt_win", "wk_n", "wk_win", "wk_win_x"]
FEATURES = NUMERIC + CATEGORICAL + EXTRA


def add_extra(df):
    """features の表に EXTRA を足す。騎手×調教師・枠は「その行より前」の結果だけで数える(日付順)。予想する出走馬(結果なし)も同じ表に入れて呼ぶ"""
    import numpy as np
    df = df.sort_values(["race_date", "race_id", "umaban"]).reset_index(drop=True)
    g = df.groupby("race_id")
    for c in REL_BASE:
        x = pd.to_numeric(df[c], errors="coerce")
        df[c + "_rk"] = x.groupby(df["race_id"]).rank(ascending=c in REL_ASC, pct=True)
        df[c + "_d"] = x - x.groupby(df["race_id"]).transform("mean")
    df["n_front"] = (pd.to_numeric(df["h5_c4_ratio"], errors="coerce") <= 0.25).groupby(df["race_id"]).transform("sum")
    win = (pd.to_numeric(df["finish"], errors="coerce") == 1).astype(float)
    jt = df["jockey_key"].astype(str) + "|" + df["trainer_key"].astype(str)
    gj = win.groupby(jt)
    df["jt_n"] = gj.cumcount()
    df["jt_win"] = (gj.cumsum() - win) / df["jt_n"].replace(0, np.nan)
    wk = df["track_code"].astype(str) + "|" + df["distance"].astype(str) + "|" + df["umaban"].astype(str)
    gw = win.groupby(wk)
    df["wk_n"] = gw.cumcount()
    df["wk_win"] = (gw.cumsum() - win) / df["wk_n"].replace(0, np.nan)
    df["wk_win_x"] = df["wk_win"] * pd.to_numeric(df["field_size"], errors="coerce")
    return df


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    con = duckdb.connect()
    build(con, sys.argv[1])
    add_extra(con.execute("SELECT * FROM features").df()).to_parquet(sys.argv[2], index=False)
    n = con.execute("SELECT count(*), count(DISTINCT race_id), min(race_date), max(race_date) FROM features").fetchone()
    print(f"特徴量: {n[0]:,}行 / {n[1]:,}レース / {n[2]}〜{n[3]} -> {sys.argv[2]}")


if __name__ == "__main__":
    main()
