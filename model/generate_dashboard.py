"""
その日の予想結果(predict.py が出力する *_predictions.csv)から、
貼り付け不要で開くだけで見られる静的HTMLダッシュボードを生成する。

v2: レース名・発走時刻・オッズ・騎手・コース特徴・馬単流し買い目案を追加。
"""
import argparse
import datetime
from pathlib import Path

import pandas as pd

SCRAPED_DIR = Path(__file__).parent.parent / "scraper" / "scraped_data"
DOCS_DIR = Path(__file__).parent.parent / "docs"
DOCS_DIR.mkdir(exist_ok=True)

# 南関東4場のコース特徴(距離別・一般的に言われる傾向。参考情報として掲載)
# 周長・直線長・回りの数値は、地方競馬情報サイト(keiba.go.jp)・oddsparkコース情報・
# 各競馬場公式ガイド等の複数情報源を突き合わせて記載(2026年8月時点)。
# 別ページ(docs/courses.html)にまとめる
TRACK_COURSE_DATA = {
    "大井": {
        "overview": "1周1600m(外回り)・直線386m。南関東4場で唯一の右回り(左回りコースも別途あり、"
                    "世界唯一の両回り競馬場としても知られる)。直線が地方競馬場全体でも最長クラスで、"
                    "他場に比べて差し・追込みも決まりやすいとされる。",
        "distances": {
            "1200m": "スタート地点からコーナーまでが短く、先行争いが激しくなりやすい。"
                      "序盤の位置取りが結果に直結しやすい距離とされる。",
            "1400m": "ワンターン(1コーナーのみ)の設定。純粋なスピード勝負になりやすく、"
                      "枠順の有利不利が比較的小さいとされる。",
            "1600m": "スタートからコーナーまでにやや余裕があり、先行馬にも差し馬にもチャンスがあるとされる。",
            "1800m": "2周に近いコース取りで、道中の脚の使いどころが問われる。持久力型が有利とされる。",
            "2000m": "スタートから1コーナーまで400m以上あり、枠順の有利不利はほぼ無いとされる。"
                      "長い直線を活かした直線一気も見られる。",
        },
    },
    "船橋": {
        "overview": "1周1400m(外回り、内回りは1250m)・直線約300m台。左回り。3・4コーナーの内外に"
                    "高低差を付けたスパイラルカーブが南関東4場で唯一の特徴。馬群がばらけやすく、"
                    "短距離戦が多いわりに逃げ馬の成績は伸び悩む傾向があるとされる。",
        "distances": {
            "1000m": "2コーナー出口付近スタート。最初のコーナーまで354mと長く、先行争いが長引くとされる。",
            "1200m": "小回りらしい先行有利の傾向が出やすい距離。内枠の逃げ・先行馬が中心視されやすい。",
            "1500m": "1コーナーまでの距離が短く、序盤の枠順・スタートが影響しやすいとされる。",
            "1600m": "スパイラルカーブを活かし、外枠からでも先行・差しの両方にチャンスがあるとされる。",
            "1700m": "4コーナーを回りきった地点からのスタートで最初の直線が長く、枠順の有利不利は少ないとされる。",
        },
    },
    "浦和": {
        "overview": "1周1200m・直線約200mで南関東4場最短。左回り。コースがコンパクトな分コーナー部分の"
                    "割合が高く、スタートから最初のコーナーまでも短いため、逃げ・先行馬が圧倒的優位とされる。",
        "distances": {
            "800m": "2コーナー出口からコースを半周するスプリント戦。直線は約200mと南関東最短で、"
                     "ほぼ先行・逃げ馬の独壇場になりやすいとされる。出遅れは致命的になりやすい。",
            "1400m": "浦和の主要距離。最初のコーナーまで約280mで、序盤の位置取りが勝負のカギとされる。",
            "1500m": "1400mよりわずかに長く、直線での差しも決まりやすくなるとされる。",
            "1600m": "コーナーを2つ回るため、コース取りの巧拙が出やすい。",
            "2000m": "長距離戦。他場以上にペース把握が重要になるとされる。",
        },
    },
    "川崎": {
        "overview": "1周1200m・直線約300mで、周長の割に直線が長め(その分コーナーが急)なのが特徴。左回り。"
                    "小回りでコーナリング技術が問われ、外を回すとロスが大きくなりやすいとされる。",
        "distances": {
            "900m": "3号スタンド前スタートで1コーナーまで300m弱と短く、内枠の先行馬に有利とされる。",
            "1400m": "川崎の主要距離の一つ。先行・差しどちらの決着も見られるバランス型とされる。",
            "1500m": "バックストレッチ中程がスタート。1コーナーまで300m弱で内枠が有利、コーナーを6回通過する"
                      "トリッキーな形態のため先行馬が有利とされる。",
            "1600m": "直線が使えるため、差し・追込みにもチャンスがある距離とされる。",
            "2100m": "4コーナー奥のポケットからスタートし1コーナーまで約500m。枠順の有利不利は少ないとされる。",
        },
    },
}
TRACK_NOTES = {t: d["overview"] for t, d in TRACK_COURSE_DATA.items()}

BASE_CSS = """
  :root{
    --paper:#f7f3ea; --paper-card:#fffdf8; --paper-deep:#efe7d3;
    --ink:#1c1a17; --ink-dim:#6b6558; --ink-faint:#a89f8c;
    --red:#b3272d; --red-dim:#7d1c20; --red-tint:#f7e6e4;
    --line:#e0d6bd; --gold:#a9832f; --gold-tint:#f5edd9;
  }
  *{box-sizing:border-box;}
  html,body{margin:0;padding:0;}
  body{background:var(--paper);
    color:var(--ink); font-family:'Zen Kaku Gothic New', sans-serif; line-height:1.7; padding:0 0 90px;}
  .wrap{max-width:920px;margin:0 auto;padding:0 20px;}

  .hero{padding:46px 20px 26px;text-align:center;border-bottom:3px solid var(--ink);position:relative;}
  .hero .eyebrow{font-family:'DM Mono', monospace;letter-spacing:0.28em;font-size:11px;color:var(--red);
    text-transform:uppercase;margin-bottom:12px;font-weight:500;}
  .hero h1{font-family:'Shippori Mincho', serif;font-weight:800;font-size:30px;margin:0 0 8px;letter-spacing:0.02em;}
  .hero .updated{font-family:'DM Mono',monospace;font-size:11.5px;color:var(--ink-faint);}
  .track-nav{display:flex;gap:10px;justify-content:center;flex-wrap:wrap;margin-top:20px;}
  .track-nav a{font-family:'Shippori Mincho',serif;font-weight:800;font-size:13px;color:var(--ink);
    border:1.5px solid var(--ink);padding:6px 16px;text-decoration:none;background:var(--paper-card);}
  .track-nav a:hover{background:var(--ink);color:var(--paper-card);}

  section.track-section{padding:34px 0 8px;border-bottom:1px solid var(--line);}
  .track-title{font-family:'Shippori Mincho',serif;font-weight:800;font-size:22px;margin:0 0 6px;
    display:flex;align-items:baseline;gap:12px;}
  .track-title .badge{font-family:'DM Mono',monospace;font-size:10.5px;color:var(--red);
    border:1px solid var(--red); border-radius:20px; padding:2px 10px;}
  .track-note{font-size:12px;color:var(--ink-dim);background:var(--paper-deep);border-radius:4px;
    padding:9px 12px;margin-bottom:20px;}
  .track-note b{color:var(--ink);}

  .race-card{background:var(--paper-card);border:1px solid var(--line);border-left:4px solid var(--ink);
    border-radius:2px;padding:18px 20px;margin-bottom:16px;box-shadow:0 1px 0 rgba(28,26,23,0.04);}
  .race-head{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:4px;flex-wrap:wrap;gap:8px;}
  .race-head .race-title{font-family:'Shippori Mincho',serif;font-weight:800;font-size:17px;}
  .race-head .race-name{font-size:13px;color:var(--ink-dim);margin-left:8px;}
  .race-head .rnum{font-family:'DM Mono',monospace;font-size:10.5px;color:var(--ink-faint);}
  .race-sub{font-family:'DM Mono',monospace;font-size:11px;color:var(--ink-faint);
    border-bottom:1px dashed var(--line);padding-bottom:10px;margin-bottom:10px;}
  .race-sub span{margin-right:14px;}

  table.pred-table{width:100%;border-collapse:collapse;font-size:13px;}
  table.pred-table th{font-family:'DM Mono',monospace;font-size:9px;letter-spacing:0.03em;color:var(--ink-faint);
    text-transform:uppercase;text-align:left;padding:6px 5px;border-bottom:1px solid var(--line);}
  table.pred-table td{padding:7px 5px;border-bottom:1px solid var(--line);white-space:nowrap;}
  table.pred-table tr:last-child td{border-bottom:none;}
  table.pred-table tr.honmei td{background:var(--red-tint);}

  .umaban{display:inline-flex;align-items:center;justify-content:center;width:24px;height:24px;
    border-radius:50%;background:var(--ink);color:var(--paper-card);font-family:'DM Mono',monospace;
    font-size:11px;font-weight:500;}
  tr.honmei .umaban{background:var(--red);}

  .pick-badge{font-family:'Shippori Mincho',serif;font-weight:800;font-size:10.5px;color:var(--paper-card);
    background:var(--red);border-radius:2px;padding:2px 7px;margin-left:5px;letter-spacing:0.05em;white-space:nowrap;}
  .pick-badge.taikou{background:var(--gold);}

  .bar-cell{display:flex;align-items:center;gap:6px;}
  .bar-track{width:50px;height:5px;background:var(--paper-deep);border-radius:3px;overflow:hidden;flex-shrink:0;}
  .bar-fill{height:100%;background:var(--red);}
  tr:not(.honmei) .bar-fill{background:var(--ink-faint);}
  .pct{font-family:'DM Mono',monospace;font-size:11.5px;color:var(--ink);}
  .odds-cell{font-family:'DM Mono',monospace;font-size:12px;color:var(--ink-dim);}

  .himo-block{margin-top:14px;padding-top:12px;border-top:1px dashed var(--line);}
  .himo-label{font-family:'DM Mono',monospace;font-size:10px;letter-spacing:0.04em;color:var(--ink-faint);
    text-transform:uppercase;margin-bottom:8px;}
  .himo-chip-row{display:flex;flex-wrap:wrap;gap:6px;}
  .himo-chip{display:inline-flex;align-items:center;gap:5px;font-family:'DM Mono',monospace;font-size:11px;
    border:1px solid var(--line);border-radius:20px;padding:3px 10px 3px 4px;background:var(--paper);}
  .himo-chip .umaban{width:18px;height:18px;font-size:9.5px;}
  .himo-chip .style-tag{color:var(--ink-dim);font-family:'Zen Kaku Gothic New',sans-serif;font-size:10.5px;}
  .himo-chip.sashi .style-tag{color:var(--red-dim);}
  .himo-chip.senko .style-tag{color:var(--gold);}

  .bet-block{margin-top:12px;padding:10px 14px;background:var(--gold-tint);border-radius:4px;
    border-left:3px solid var(--gold);}
  .bet-label{font-family:'DM Mono',monospace;font-size:10px;letter-spacing:0.04em;color:var(--gold);
    text-transform:uppercase;margin-bottom:4px;font-weight:500;}
  .bet-line{font-family:'DM Mono',monospace;font-size:13.5px;color:var(--ink);font-weight:500;}
  .bet-line .arrow{color:var(--ink-faint);margin:0 4px;}

  .triple-block{background:var(--ink);color:var(--paper-card);border-radius:6px;padding:18px 20px;margin-bottom:20px;}
  .triple-title{font-family:'Shippori Mincho',serif;font-weight:800;font-size:15px;margin-bottom:6px;color:var(--gold);}
  .triple-desc{font-size:11.5px;color:#c9c2b0;margin-bottom:14px;}
  .triple-legs{display:flex;gap:14px;flex-wrap:wrap;}
  .triple-leg{background:rgba(255,255,255,0.06);border-radius:4px;padding:10px 14px;min-width:110px;}
  .triple-leg-r{font-family:'DM Mono',monospace;font-size:10px;color:#c9c2b0;margin-bottom:4px;}
  .triple-leg-bet{font-family:'DM Mono',monospace;font-size:16px;font-weight:500;color:var(--paper-card);}
  .triple-leg-bet .arrow{color:var(--gold);margin:0 4px;}
  .triple-leg-alt{font-family:'DM Mono',monospace;font-size:10px;color:#a89f8c;margin-top:4px;}

  .empty{text-align:center;padding:70px 20px;color:var(--ink-faint);font-family:'Shippori Mincho',serif;font-size:15px;}
  .disclaimer{font-size:11px;color:var(--ink-faint);text-align:center;padding:20px 20px 0;max-width:640px;margin:0 auto;}
  footer{padding:20px 20px 0;text-align:center;color:var(--ink-faint);font-size:11px;font-family:'DM Mono',monospace;}
  .table-scroll-hint{display:none;font-family:'DM Mono',monospace;font-size:10px;color:var(--ink-faint);margin-bottom:4px;}


  @media (max-width: 480px){
    .hero{padding:32px 16px 20px;}
    .hero h1{font-size:22px;}
    .hero .eyebrow{font-size:9.5px;letter-spacing:0.18em;}
    .track-nav{gap:6px;}
    .track-nav a{font-size:11.5px;padding:5px 11px;}
    .track-section{padding:22px 0 4px;}
    .track-title{font-size:18px;}
    .race-card{padding:14px 12px;margin-bottom:12px;}
    .race-head .race-title{font-size:15px;}
    .race-head .race-name{display:block;margin-left:0;font-size:12px;}
    .race-sub{font-size:10px;}
    .race-sub span{margin-right:8px;display:inline-block;}
    table.pred-table{display:block;overflow-x:auto;-webkit-overflow-scrolling:touch;
      font-size:11px;white-space:nowrap;}
    table.pred-table th, table.pred-table td{padding:6px 5px;}
    .table-scroll-hint{display:block;}
    .bar-track{width:32px;}
    .odds-cell{font-size:10px;}
    .himo-chip-row{gap:5px;}
    .himo-chip{font-size:10px;padding:2px 8px 2px 3px;}
    .bet-block, .triple-block{padding:12px 14px;}
  }
  @media (max-width: 340px){
    .wrap{padding:0 12px;}
  }
"""


EMPTY_TEMPLATE = """
<div class="empty">
  <p>この日は南関東4場(大井・船橋・浦和・川崎)の開催がありませんでした。</p>
</div>
"""


def style_tag_from_gain(gain) -> tuple:
    """corner_gain(初角-最終角の平均)から脚質タグとCSSクラスを決める。"""
    if gain is None or pd.isna(gain):
        return ("―", "")
    if gain >= 1.5:
        return (f"差し込み型 (+{gain:.1f})", "sashi")
    if gain <= -1.5:
        return (f"先行粘り込み型 ({gain:.1f})", "senko")
    return (f"平均的 ({gain:+.1f})", "")


def fmt_odds(odds) -> str:
    if odds is None or pd.isna(odds):
        return "―"
    return f"{odds:.1f}倍"


def fmt(val, default="―"):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return default
    return str(val)


def build_race_card_html(race_id: str, race_num: int, df_race: pd.DataFrame) -> str:
    df_race = df_race.sort_values("rank")
    head = df_race.iloc[0]

    race_name = fmt(head.get("race_name"), "")
    post_time = fmt(head.get("post_time"), "")
    grade = fmt(head.get("grade"))
    surface = fmt(head.get("surface"))
    distance = head.get("distance")
    distance_str = f"{int(distance)}m" if distance and not pd.isna(distance) else "―"
    weather = fmt(head.get("weather"))
    baba = fmt(head.get("baba_condition"))

    rows_html = []
    for _, row in df_race.iterrows():
        rank = int(row["rank"])
        row_class = "honmei" if rank == 1 else ("taikou" if rank == 2 else "")
        badge = ""
        if rank == 1:
            badge = '<span class="pick-badge">本命</span>'
        elif rank == 2:
            badge = '<span class="pick-badge taikou">対抗</span>'
        win_pct = row["p_win"] * 100
        top3_pct = row["p_top3"] * 100
        sei_rei = f"{fmt(row.get('sei'),'')}{fmt(row.get('rei'),'')}" if row.get('sei') else "―"
        waku = fmt(row.get('waku'))
        avg_ninki = row.get('avg5_ninki')
        avg_ninki_str = f"{avg_ninki:.1f}人気" if pd.notna(avg_ninki) else "―"
        avg_last3f = row.get('avg5_last3f')
        avg_last3f_str = f"{avg_last3f:.1f}秒" if pd.notna(avg_last3f) else "―"
        days = row.get('days_since_last')
        weeks_str = f"{int(days/7)}週" if pd.notna(days) else "―"
        n_past = row.get('n_past_races')
        n_past_str = f"{int(n_past)}走分" if pd.notna(n_past) else "データなし"
        rows_html.append(f"""
        <tr class="{row_class}">
          <td>{waku}</td>
          <td><span class="umaban">{row['馬番']}</span></td>
          <td>{row['horse_name']}{badge}</td>
          <td>{sei_rei} / {fmt(row.get('kinryo'))}kg</td>
          <td>{fmt(row.get('jockey'))}</td>
          <td class="odds-cell">{fmt_odds(row.get('odds'))}{' (' + str(int(row['ninki'])) + '人気)' if pd.notna(row.get('ninki')) else ''}</td>
          <td class="odds-cell">直近{avg_ninki_str} / 上3F平均{avg_last3f_str} / 休養{weeks_str} ({n_past_str})</td>
          <td><div class="bar-cell"><div class="bar-track"><div class="bar-fill" style="width:{min(win_pct*3,100):.0f}%"></div></div><span class="pct">{win_pct:.1f}%</span></div></td>
          <td><div class="bar-cell"><div class="bar-track"><div class="bar-fill" style="width:{top3_pct:.0f}%"></div></div><span class="pct">{top3_pct:.1f}%</span></div></td>
        </tr>""")

    # 紐(2〜3着候補)ブロック
    df_himo = df_race[df_race["rank"] != 1].sort_values("p_top3", ascending=False).head(5)
    himo_chips = []
    himo_partners = []
    for _, row in df_himo.iterrows():
        tag, css_class = style_tag_from_gain(row.get("corner_gain"))
        himo_chips.append(f"""
        <span class="himo-chip {css_class}">
          <span class="umaban">{row['馬番']}</span>
          <span class="style-tag">{tag}</span>
        </span>""")
        himo_partners.append(str(int(row["馬番"])))
    himo_block = f"""
      <div class="himo-block">
        <div class="himo-label">紐候補(複勝率順・脚質)</div>
        <div class="himo-chip-row">{''.join(himo_chips)}</div>
      </div>""" if himo_chips else ""

    # 馬単流し買い目案(本命を軸に、上位3頭の紐候補へ流す)
    axis = int(head["馬番"])
    partners_top = himo_partners[:3]
    bet_block = ""
    if partners_top:
        bet_block = f"""
      <div class="bet-block">
        <div class="bet-label">買い目案(馬単1着流し・{len(partners_top)}点)</div>
        <div class="bet-line">{axis}<span class="arrow">→</span>{', '.join(partners_top)}</div>
      </div>"""

    return f"""
    <div class="race-card">
      <div class="race-head">
        <span><span class="race-title">{race_num}R</span><span class="race-name">{race_name}</span></span>
        <span class="rnum">race_id: {race_id}</span>
      </div>
      <div class="race-sub">
        <span>発走 {post_time}</span>
        <span>{grade}</span>
        <span>{surface}{distance_str}</span>
        <span>天候:{weather}</span>
        <span>馬場:{baba}</span>
      </div>
      <table class="pred-table">
        <caption class="table-scroll-hint">← 横にスクロールできます →</caption>
        <thead><tr><th>枠</th><th>馬番</th><th>馬名</th><th>性齢/斤量</th><th>騎手</th><th>単勝オッズ</th><th>直近フォーム</th><th>単勝率</th><th>複勝率</th></tr></thead>
        <tbody>{''.join(rows_html)}</tbody>
      </table>
      {himo_block}
      {bet_block}
    </div>"""


HOME_TEMPLATE = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>南関東競馬AI予想 - {date}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Shippori+Mincho:wght@600;800&family=Zen+Kaku+Gothic+New:wght@400;500;700;900&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
{base_css}
  .track-block{{padding:28px 0;border-bottom:1px solid var(--line);}}
  .track-block-head{{display:flex;align-items:baseline;justify-content:space-between;margin-bottom:6px;flex-wrap:wrap;gap:8px;}}
  .track-block-head h2{{font-family:'Shippori Mincho',serif;font-weight:800;font-size:20px;margin:0;}}
  .track-note-mini{{font-size:11.5px;color:var(--ink-dim);margin-bottom:14px;}}
  .race-grid{{display:grid;grid-template-columns:repeat(auto-fill, minmax(96px, 1fr));gap:10px;}}
  .race-tile{{display:block;background:var(--paper-card);border:1px solid var(--line);border-radius:6px;
    padding:12px 8px;text-align:center;text-decoration:none;color:var(--ink);
    transition:transform 0.08s ease;}}
  .race-tile:active{{transform:scale(0.96);}}
  .race-tile:hover{{border-color:var(--red);}}
  .race-tile .rn{{font-family:'Shippori Mincho',serif;font-weight:800;font-size:18px;display:block;}}
  .race-tile .rtime{{font-family:'DM Mono',monospace;font-size:10px;color:var(--ink-faint);display:block;margin-top:3px;}}
  .race-tile .rhonmei{{font-size:10.5px;color:var(--red);display:block;margin-top:4px;font-weight:500;}}
  .top-links{{display:flex;gap:10px;justify-content:center;flex-wrap:wrap;margin-top:20px;}}
  .top-links a{{font-family:'DM Mono',monospace;font-size:12px;color:var(--ink);border:1px solid var(--line);
    padding:6px 16px;border-radius:20px;text-decoration:none;background:var(--paper-card);}}
  .top-links a:hover{{border-color:var(--red);color:var(--red);}}
</style>
</head>
<body>

<div class="hero">
  <div class="wrap">
    <div class="eyebrow">South Kanto NAR AI · Daily Report</div>
    <h1>南関東競馬AI予想</h1>
    <div class="updated">{date} 分 · 最終更新: {generated_at}</div>
    <div class="top-links">
      <a href="triple.html">トリプル馬単 →</a>
      <a href="courses.html">コース特徴 →</a>
    </div>
  </div>
</div>

<div class="wrap">
{content}
</div>

<footer>keiba_ai (南関東版) · model_early_urawa · 毎朝GitHub Actionsで自動更新</footer>

</body>
</html>
"""

RACE_PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{track} {race_num}R 予想 - {date}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Shippori+Mincho:wght@600;800&family=Zen+Kaku+Gothic+New:wght@400;500;700;900&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
{base_css}
  .page-nav{{max-width:920px;margin:0 auto;padding:16px 20px 0;display:flex;justify-content:space-between;
    align-items:center;flex-wrap:wrap;gap:10px;}}
  .page-nav a{{font-family:'DM Mono',monospace;font-size:12px;color:var(--ink);border:1px solid var(--line);
    padding:5px 14px;border-radius:20px;text-decoration:none;background:var(--paper-card);}}
  .page-nav a:hover{{border-color:var(--red);color:var(--red);}}
  .race-num-nav{{display:flex;gap:6px;flex-wrap:wrap;}}
  .race-num-nav a{{padding:4px 10px;font-size:11px;}}
  .race-num-nav a.current{{background:var(--ink);color:var(--paper-card);border-color:var(--ink);}}
</style>
</head>
<body>

<div class="page-nav">
  <a href="../index.html">← ホームに戻る</a>
  <div class="race-num-nav">{race_num_nav}</div>
</div>

<div class="wrap" style="padding-top:20px;">
  <h1 style="font-family:'Shippori Mincho',serif;font-weight:800;font-size:22px;margin:0 0 4px;">{track}</h1>
  <p style="font-size:12px;color:var(--ink-dim);margin:0 0 20px;">{date} 分</p>
{content}
</div>

<footer>keiba_ai (南関東版) · model_early_urawa</footer>

</body>
</html>
"""


def generate_dashboard(date_str: str) -> Path:
    pred_path = SCRAPED_DIR / f"{date_str}_racecards_raw_predictions.csv"
    out_path = DOCS_DIR / "index.html"
    races_dir = DOCS_DIR / "races"
    races_dir.mkdir(exist_ok=True)

    generated_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    if not pred_path.exists():
        html = HOME_TEMPLATE.format(
            date=date_str, generated_at=generated_at, base_css=BASE_CSS, content=EMPTY_TEMPLATE,
        )
        out_path.write_text(html, encoding="utf-8")
        generate_courses_page()
        return out_path

    df = pd.read_csv(pred_path)
    tracks = sorted(df["track"].unique())

    home_sections = []
    for track in tracks:
        df_track = df[df["track"] == track]
        race_nums = sorted(df_track["race_num"].unique())

        # レース番号ナビ(個別ページの上部で使う、同じ場の全レースへのショートカット)
        race_num_nav = " ".join(
            f'<a href="{track}_{rn}.html" class="{"current" if False else ""}">{rn}R</a>' for rn in race_nums
        )

        tiles = []
        for rn in race_nums:
            df_race = df_track[df_track["race_num"] == rn]
            head = df_race.sort_values("rank").iloc[0]
            post_time = fmt(head.get("post_time"), "")
            honmei_name = fmt(head.get("horse_name"), "")
            tiles.append(f"""
            <a class="race-tile" href="races/{track}_{rn}.html">
              <span class="rn">{rn}R</span>
              <span class="rtime">{post_time}</span>
              <span class="rhonmei">◎{honmei_name}</span>
            </a>""")

        note = TRACK_NOTES.get(track, "")
        home_sections.append(f"""
        <section class="track-block">
          <div class="track-block-head"><h2>{track}</h2>
            <a href="courses.html#{track}" style="font-size:11px;color:var(--red);">コース特徴 →</a></div>
          <p class="track-note-mini">{note}</p>
          <div class="race-grid">{''.join(tiles)}</div>
        </section>""")

        # 個別レースページを生成
        for rn in race_nums:
            df_race = df_track[df_track["race_num"] == rn]
            race_id = str(df_race.iloc[0]["race_id"])
            card_html = build_race_card_html(race_id, rn, df_race)
            nav_html = " ".join(
                f'<a href="{track}_{r}.html" class="{"current" if r == rn else ""}">{r}R</a>' for r in race_nums
            )
            race_html = RACE_PAGE_TEMPLATE.format(
                track=track, race_num=rn, date=date_str, base_css=BASE_CSS,
                race_num_nav=nav_html, content=card_html,
            )
            (races_dir / f"{track}_{rn}.html").write_text(race_html, encoding="utf-8")

    html = HOME_TEMPLATE.format(
        date=date_str, generated_at=generated_at, base_css=BASE_CSS, content="".join(home_sections),
    )
    out_path.write_text(html, encoding="utf-8")
    generate_courses_page()
    generate_triple_umatan_page(df, date_str)
    return out_path


def build_umatan_formation(df_race: pd.DataFrame) -> dict:
    """1レース分の馬単フォーメーション(1着候補×2着候補)を組み立てる。
    1着候補: 単勝率トップ3(本命・対抗・単穴)
    2着候補: 複勝率トップ5(1着候補と重複する馬は除いてカウント)
    → 最大3×5=15点程度(重複除外で実際は12〜15点)のフォーメーション。
    """
    df_sorted = df_race.sort_values("rank")
    first_candidates = df_sorted.head(3)
    first_umaban = first_candidates["馬番"].astype(int).tolist()

    second_pool = df_race.sort_values("p_top3", ascending=False)
    second_candidates = second_pool.head(6)
    second_umaban = [u for u in second_candidates["馬番"].astype(int).tolist()][:5]

    combos = []
    for f in first_umaban:
        for s in second_umaban:
            if f != s:
                combos.append((f, s))

    return {
        "first": first_umaban,
        "second": second_umaban,
        "combos": combos,
    }


def generate_triple_umatan_page(df: pd.DataFrame, date_str: str):
    """トリプル馬単(各場の最終3レースの馬単フォーメーションを3連続的中させる企画)の
    専用ページを生成する。"""
    tracks = sorted(df["track"].unique())
    sections = []
    for track in tracks:
        df_track = df[df["track"] == track]
        race_nums = sorted(df_track["race_num"].unique())
        if len(race_nums) < 3:
            continue
        target_races = race_nums[-3:]
        legs_html = []
        total_combo_count = 1
        for rn in target_races:
            df_race = df_track[df_track["race_num"] == rn]
            formation = build_umatan_formation(df_race)
            total_combo_count *= max(len(formation["combos"]), 1)
            combo_str = "、".join(f"{f}→{s}" for f, s in formation["combos"])
            legs_html.append(f"""
        <div class="leg-card">
          <div class="leg-r">{rn}R</div>
          <div class="leg-formation">
            <span class="formation-label">1着</span>
            <span class="formation-nums">{' '.join(str(x) for x in formation['first'])}</span>
            <span class="arrow">→</span>
            <span class="formation-label">2着</span>
            <span class="formation-nums">{' '.join(str(x) for x in formation['second'])}</span>
          </div>
          <div class="leg-combos">{combo_str}({len(formation['combos'])}点)</div>
        </div>""")
        race_range = f"{target_races[0]}〜{target_races[-1]}R"
        sections.append(f"""
        <section class="track-block" id="{track}">
          <h2 class="track-h">{track} <span class="range-badge">{race_range}</span></h2>
          <p class="total-combo">3レース合計 {total_combo_count} 通り
            (各レースの馬単フォーメーションから1点ずつ選んで3連続的中を狙う)</p>
          <div class="legs-row">{''.join(legs_html)}</div>
        </section>""")

    content = "".join(sections) if sections else '<p class="empty">対象レース(3R以上開催の場)がありません。</p>'
    html = TRIPLE_HTML_TEMPLATE.format(date=date_str, content=content)
    (DOCS_DIR / "triple.html").write_text(html, encoding="utf-8")


TRIPLE_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>南関東競馬 トリプル馬単 - {date}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Shippori+Mincho:wght@600;800&family=Zen+Kaku+Gothic+New:wght@400;500;700;900&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root{{
    --paper:#f7f3ea; --paper-card:#fffdf8; --ink:#1c1a17; --ink-dim:#6b6558; --ink-faint:#a89f8c;
    --gold:#a9832f; --line:#e0d6bd;
  }}
  *{{box-sizing:border-box;}}
  html,body{{margin:0;padding:0;}}
  body{{background:var(--ink);color:var(--paper-card);font-family:'Zen Kaku Gothic New', sans-serif;
    line-height:1.7;padding:0 0 80px;}}
  .wrap{{max-width:880px;margin:0 auto;padding:0 20px;}}
  .hero{{padding:44px 20px 24px;text-align:center;border-bottom:2px solid var(--gold);}}
  .hero .eyebrow{{font-family:'DM Mono',monospace;letter-spacing:0.28em;font-size:11px;color:var(--gold);
    text-transform:uppercase;margin-bottom:10px;}}
  .hero h1{{font-family:'Shippori Mincho',serif;font-weight:800;font-size:26px;margin:0 0 6px;color:var(--paper-card);}}
  .hero p{{font-size:12.5px;color:#c9c2b0;max-width:540px;margin:8px auto 0;}}
  .back-link{{display:inline-block;margin-top:16px;font-family:'DM Mono',monospace;font-size:12px;
    color:var(--paper-card);border:1.5px solid var(--paper-card);padding:5px 14px;text-decoration:none;}}
  .back-link:hover{{background:var(--paper-card);color:var(--ink);}}
  section.track-block{{padding:30px 0;border-bottom:1px solid rgba(255,255,255,0.12);}}
  .track-h{{font-family:'Shippori Mincho',serif;font-weight:800;font-size:20px;margin:0 0 6px;
    display:flex;align-items:baseline;gap:10px;}}
  .range-badge{{font-family:'DM Mono',monospace;font-size:11px;color:var(--gold);border:1px solid var(--gold);
    border-radius:20px;padding:2px 10px;}}
  .total-combo{{font-size:12px;color:#c9c2b0;margin-bottom:16px;}}
  .legs-row{{display:flex;gap:14px;flex-wrap:wrap;}}
  .leg-card{{background:rgba(255,255,255,0.05);border-radius:6px;padding:14px 16px;flex:1;min-width:220px;}}
  .leg-r{{font-family:'DM Mono',monospace;font-size:11px;color:#c9c2b0;margin-bottom:8px;}}
  .leg-formation{{display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-bottom:8px;}}
  .formation-label{{font-family:'DM Mono',monospace;font-size:9.5px;color:var(--gold);}}
  .formation-nums{{font-family:'DM Mono',monospace;font-size:15px;color:var(--paper-card);font-weight:500;}}
  .leg-formation .arrow{{color:var(--gold);}}
  .leg-combos{{font-family:'DM Mono',monospace;font-size:10.5px;color:#a89f8c;line-height:1.6;}}
  .empty{{text-align:center;padding:60px 20px;color:#a89f8c;}}
  .disclaimer{{font-size:11px;color:#a89f8c;text-align:center;padding:26px 20px 0;max-width:600px;margin:0 auto;}}
  @media (max-width: 480px){{
    .hero{{padding:32px 16px 20px;}}
    .hero h1{{font-size:22px;}}
    .hero p{{font-size:11.5px;}}
    .track-h{{font-size:17px;}}
    .legs-row{{flex-direction:column;}}
    .leg-card{{min-width:auto;}}
  }}
</style>
</head>
<body>
<div class="hero">
  <div class="wrap">
    <div class="eyebrow">South Kanto NAR AI · SPAT4</div>
    <h1>トリプル馬単</h1>
    <p>各場の最終3レースの馬単を3連続的中させる企画。1着候補(本命・対抗)×2着候補(複勝率上位)の
      フォーメーションを、各レースごとに提示します。</p>
    <a class="back-link" href="index.html">← 本日の予想に戻る</a>
  </div>
</div>
<div class="wrap">
{content}
<p class="disclaimer">
  フォーメーションはAI予想確率に基づく機械的な提案です。的中を保証するものではありません。
  投票の最終判断はご自身の責任で行ってください。
</p>
</div>
</body>
</html>
"""


COURSES_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>南関東競馬 コース特徴(距離別)</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Shippori+Mincho:wght@600;800&family=Zen+Kaku+Gothic+New:wght@400;500;700;900&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root{{
    --paper:#f7f3ea; --paper-card:#fffdf8; --paper-deep:#efe7d3;
    --ink:#1c1a17; --ink-dim:#6b6558; --ink-faint:#a89f8c;
    --red:#b3272d; --line:#e0d6bd;
  }}
  *{{box-sizing:border-box;}}
  html,body{{margin:0;padding:0;}}
  body{{background:var(--paper);color:var(--ink);font-family:'Zen Kaku Gothic New', sans-serif;
    line-height:1.7;padding:0 0 80px;}}
  .wrap{{max-width:820px;margin:0 auto;padding:0 20px;}}
  .hero{{padding:44px 20px 24px;text-align:center;border-bottom:3px solid var(--ink);}}
  .hero .eyebrow{{font-family:'DM Mono',monospace;letter-spacing:0.28em;font-size:11px;color:var(--red);
    text-transform:uppercase;margin-bottom:10px;}}
  .hero h1{{font-family:'Shippori Mincho',serif;font-weight:800;font-size:26px;margin:0 0 6px;}}
  .back-link{{display:inline-block;margin-top:16px;font-family:'DM Mono',monospace;font-size:12px;
    color:var(--ink);border:1.5px solid var(--ink);padding:5px 14px;text-decoration:none;background:var(--paper-card);}}
  .back-link:hover{{background:var(--ink);color:var(--paper-card);}}
  section.track-block{{padding:30px 0;border-bottom:1px solid var(--line);}}
  .track-h{{font-family:'Shippori Mincho',serif;font-weight:800;font-size:21px;margin:0 0 8px;}}
  .track-overview{{font-size:13.5px;color:var(--ink-dim);margin-bottom:18px;}}
  .dist-card{{background:var(--paper-card);border:1px solid var(--line);border-left:3px solid var(--red);
    border-radius:2px;padding:12px 16px;margin-bottom:10px;}}
  .dist-name{{font-family:'DM Mono',monospace;font-size:13px;color:var(--red);margin-bottom:4px;font-weight:500;}}
  .dist-desc{{font-size:13px;color:var(--ink);}}
  .disclaimer{{font-size:11px;color:var(--ink-faint);text-align:center;padding:26px 20px 0;}}
  .track-svg-wrap{{background:var(--paper-card);border:1px solid var(--line);border-radius:6px;
    padding:14px;margin-bottom:16px;text-align:center;}}
  .track-svg-wrap svg{{max-width:100%;height:auto;}}
  .svg-caption{{font-family:'DM Mono',monospace;font-size:10px;color:var(--ink-faint);margin-top:6px;}}
  @media (max-width: 480px){{
    .hero{{padding:32px 16px 20px;}}
    .hero h1{{font-size:21px;}}
    .track-h{{font-size:18px;}}
    .dist-card{{padding:10px 12px;}}
  }}
</style>
</head>
<body>
<div class="hero">
  <div class="wrap">
    <div class="eyebrow">South Kanto NAR AI</div>
    <h1>コース特徴(距離別)</h1>
    <a class="back-link" href="index.html">← 本日の予想に戻る</a>
  </div>
</div>
<div class="wrap">
{content}
<p class="disclaimer">記載内容は一般的に言われている傾向をまとめた参考情報です。
  厳密な公式データに基づく検証済みの数値ではありません。</p>
</div>
</body>
</html>
"""


# 各場の模式的な周長(概念図の縮尺計算専用の仮定値。実測値ではありません)
# 各場の実測値ベースの周長・直線長・回り(出典: keiba.go.jp、oddspark、各競馬場公式ガイド等の複数情報を突き合わせ)
# 大井のみ南関東4場で唯一の右回り(左回りコースも別途あり、世界唯一の両回り競馬場)。他3場は左回り。
TRACK_LAP_LENGTH = {"大井": 1600, "船橋": 1400, "浦和": 1200, "川崎": 1200}
TRACK_HOME_STRETCH = {"大井": 386, "船橋": 310, "浦和": 200, "川崎": 300}
TRACK_TURN = {"大井": "right", "船橋": "left", "浦和": "left", "川崎": "left"}


def generate_track_svg(distance_m: int, lap_length: int, turn: str = "left") -> str:
    """スタート位置とゴールの相対関係を示す概念図(模式図)をSVGで生成する。
    実際のコース形状・縮尺とは異なる簡略化された図であることに注意。
    """
    W, H = 320, 180
    straight = 110  # 直線部の長さ(描画上のユニット)
    radius = 45     # コーナー部の半径(描画上のユニット)
    cx, cy = W / 2, H / 2

    # オーバル(競馬場)のパス長(描画ユニット)。周長に対応させる。
    import math
    turn_len = math.pi * radius
    total_path_units = 2 * straight + 2 * turn_len

    # ゴール(直線の終端、右下寄り)からdistance_m分だけ逆走した位置にスタート地点を置く
    frac = min(distance_m / lap_length, 1.0) if lap_length else 0
    dist_units = frac * total_path_units

    # ゴール地点(下直線の右端)を基準に、反時計回り(逆走)でスタート位置を求める
    goal_x, goal_y = cx + straight / 2, cy + radius
    remaining = dist_units
    if remaining <= straight:
        start_x = goal_x - remaining
        start_y = goal_y
    else:
        remaining -= straight
        if remaining <= turn_len:
            angle = (remaining / turn_len) * math.pi
            start_x = cx - straight / 2 - radius * math.sin(angle)
            start_y = cy + radius * math.cos(angle)
        else:
            remaining -= turn_len
            if remaining <= straight:
                start_x = cx - straight / 2 - remaining
                start_y = cy - radius
            else:
                remaining -= straight
                angle = math.pi + (remaining / turn_len) * math.pi
                start_x = cx + straight / 2 - radius * math.sin(angle)
                start_y = cy - radius * math.cos(angle)

    mirror_open = f'<g transform="translate({W},0) scale(-1,1)">' if turn == "right" else '<g>'
    goal_x_disp = (W - goal_x) if turn == "right" else goal_x
    start_x_disp = (W - start_x) if turn == "right" else start_x

    return f"""<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg">
  <rect x="0" y="0" width="{W}" height="{H}" fill="#fffdf8"/>
  {mirror_open}
  <path d="M {cx - straight/2} {cy - radius}
           L {cx + straight/2} {cy - radius}
           A {radius} {radius} 0 0 1 {cx + straight/2} {cy + radius}
           L {cx - straight/2} {cy + radius}
           A {radius} {radius} 0 0 1 {cx - straight/2} {cy - radius}"
        fill="none" stroke="#1c1a17" stroke-width="10" stroke-linecap="round"/>
  <path d="M {cx - straight/2} {cy - radius}
           L {cx + straight/2} {cy - radius}
           A {radius} {radius} 0 0 1 {cx + straight/2} {cy + radius}
           L {cx - straight/2} {cy + radius}
           A {radius} {radius} 0 0 1 {cx - straight/2} {cy - radius}"
        fill="none" stroke="#efe7d3" stroke-width="6" stroke-linecap="round"/>
  </g>
  <line x1="{goal_x_disp}" y1="{cy + radius - 14}" x2="{goal_x_disp}" y2="{cy + radius + 14}" stroke="#b3272d" stroke-width="3"/>
  <text x="{goal_x_disp}" y="{cy + radius + 28}" font-family="monospace" font-size="10" fill="#b3272d" text-anchor="middle">ゴール</text>
  <circle cx="{start_x_disp:.1f}" cy="{start_y:.1f}" r="6" fill="#a9832f"/>
  <text x="{start_x_disp:.1f}" y="{start_y - 12:.1f}" font-family="monospace" font-size="10" fill="#a9832f" text-anchor="middle">スタート</text>
  <text x="{cx}" y="{cy}" font-family="monospace" font-size="13" fill="#6b6558" text-anchor="middle" font-weight="bold">{distance_m}m</text>
  <text x="{cx}" y="{H - 8}" font-family="monospace" font-size="9" fill="#a89f8c" text-anchor="middle">{'右回り' if turn=='right' else '左回り'}(進行方向は概念的に表示)</text>
</svg>"""


def generate_courses_page():
    sections = []
    for track, data in TRACK_COURSE_DATA.items():
        lap_length = TRACK_LAP_LENGTH.get(track, 1500)
        dist_cards = []
        for dist, desc in data["distances"].items():
            distance_m = int(dist.replace("m", ""))
            svg = generate_track_svg(distance_m, lap_length, TRACK_TURN.get(track, "left"))
            dist_cards.append(f"""
            <div class="dist-card">
              <div class="dist-name">{dist}</div>
              <div class="track-svg-wrap">{svg}<div class="svg-caption">スタート位置の概念図(模式図・実際の形状/縮尺とは異なります)</div></div>
              <div class="dist-desc">{desc}</div>
            </div>""")
        sections.append(f"""
        <section class="track-block" id="{track}">
          <h2 class="track-h">{track}</h2>
          <p class="track-overview">{data['overview']}</p>
          {''.join(dist_cards)}
        </section>""")
    html = COURSES_HTML_TEMPLATE.format(content="".join(sections))
    (DOCS_DIR / "courses.html").write_text(html, encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="日次予想ダッシュボードHTML生成")
    parser.add_argument("--date", default=datetime.date.today().isoformat())
    args, _unknown = parser.parse_known_args()

    out = generate_dashboard(args.date)
    print(f"生成: {out}")
