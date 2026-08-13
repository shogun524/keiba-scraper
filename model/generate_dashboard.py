"""
その日の予想結果(predict.py が出力する *_predictions.csv)から、
貼り付け不要で開くだけで見られる静的HTMLダッシュボードを生成する。

競輪AIのGitHub Pages自動更新の仕組みと同じ考え方:
  スクレイピング → 予想 → HTML生成 → コミット → GitHub Pagesが自動反映

使い方:
    python generate_dashboard.py --date 2026-08-14
    (../scraper/scraped_data/2026-08-14_racecards_raw_predictions.csv を読み込んで
     docs/index.html を生成する)
"""
import sys
import argparse
import datetime
from pathlib import Path

import pandas as pd

SCRAPED_DIR = Path(__file__).parent.parent / "scraper" / "scraped_data"
DOCS_DIR = Path(__file__).parent.parent / "docs"
DOCS_DIR.mkdir(exist_ok=True)

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>南関東競馬AI予想 - {date}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Shippori+Mincho:wght@600;800&family=Zen+Kaku+Gothic+New:wght@400;500;700;900&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root{{
    --paper:#f7f3ea; --paper-card:#fffdf8; --paper-deep:#efe7d3;
    --ink:#1c1a17; --ink-dim:#6b6558; --ink-faint:#a89f8c;
    --red:#b3272d; --red-dim:#7d1c20; --red-tint:#f7e6e4;
    --line:#e0d6bd; --gold:#a9832f;
  }}
  *{{box-sizing:border-box;}}
  html,body{{margin:0;padding:0;}}
  body{{background:var(--paper);
    color:var(--ink); font-family:'Zen Kaku Gothic New', sans-serif; line-height:1.7; padding:0 0 90px;}}
  .wrap{{max-width:900px;margin:0 auto;padding:0 20px;}}

  .hero{{padding:46px 20px 26px;text-align:center;border-bottom:3px solid var(--ink);position:relative;}}
  .hero::after{{content:"";position:absolute;left:0;right:0;bottom:-7px;height:1px;background:var(--ink);opacity:0.5;}}
  .hero .eyebrow{{font-family:'DM Mono', monospace;letter-spacing:0.28em;font-size:11px;color:var(--red);
    text-transform:uppercase;margin-bottom:12px;font-weight:500;}}
  .hero h1{{font-family:'Shippori Mincho', serif;font-weight:800;font-size:30px;margin:0 0 8px;
    letter-spacing:0.02em;}}
  .hero .updated{{font-family:'DM Mono',monospace;font-size:11.5px;color:var(--ink-faint);}}
  .track-nav{{display:flex;gap:10px;justify-content:center;flex-wrap:wrap;margin-top:20px;}}
  .track-nav a{{font-family:'Shippori Mincho',serif;font-weight:800;font-size:13px;color:var(--ink);
    border:1.5px solid var(--ink);padding:6px 16px;text-decoration:none;background:var(--paper-card);}}
  .track-nav a:hover{{background:var(--ink);color:var(--paper-card);}}

  section.track-section{{padding:34px 0 8px;border-bottom:1px solid var(--line);}}
  .track-title{{font-family:'Shippori Mincho',serif;font-weight:800;font-size:22px;margin:0 0 18px;
    display:flex;align-items:baseline;gap:12px;}}
  .track-title .badge{{font-family:'DM Mono',monospace;font-size:10.5px;color:var(--red);
    border:1px solid var(--red); border-radius:20px; padding:2px 10px;}}

  .race-card{{background:var(--paper-card);border:1px solid var(--line);border-left:4px solid var(--ink);
    border-radius:2px;padding:18px 20px;margin-bottom:16px;box-shadow:0 1px 0 rgba(28,26,23,0.04);}}
  .race-head{{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:12px;
    border-bottom:1px dashed var(--line);padding-bottom:10px;}}
  .race-head .race-title{{font-family:'Shippori Mincho',serif;font-weight:800;font-size:17px;}}
  .race-head .rnum{{font-family:'DM Mono',monospace;font-size:10.5px;color:var(--ink-faint);}}

  table.pred-table{{width:100%;border-collapse:collapse;font-size:13.5px;}}
  table.pred-table th{{font-family:'DM Mono',monospace;font-size:9.5px;letter-spacing:0.04em;color:var(--ink-faint);
    text-transform:uppercase;text-align:left;padding:6px 6px;border-bottom:1px solid var(--line);}}
  table.pred-table td{{padding:8px 6px;border-bottom:1px solid var(--line);}}
  table.pred-table tr:last-child td{{border-bottom:none;}}
  table.pred-table tr.honmei td{{background:var(--red-tint);}}

  .umaban{{display:inline-flex;align-items:center;justify-content:center;width:26px;height:26px;
    border-radius:50%;background:var(--ink);color:var(--paper-card);font-family:'DM Mono',monospace;
    font-size:12px;font-weight:500;}}
  tr.honmei .umaban{{background:var(--red);}}

  .pick-badge{{font-family:'Shippori Mincho',serif;font-weight:800;font-size:11px;color:var(--paper-card);
    background:var(--red);border-radius:2px;padding:2px 8px;margin-left:6px;letter-spacing:0.05em;}}
  .pick-badge.taikou{{background:var(--gold);}}

  .bar-cell{{display:flex;align-items:center;gap:7px;}}
  .bar-track{{width:64px;height:5px;background:var(--paper-deep);border-radius:3px;overflow:hidden;flex-shrink:0;}}
  .bar-fill{{height:100%;background:var(--red);}}
  tr:not(.honmei) .bar-fill{{background:var(--ink-faint);}}
  .pct{{font-family:'DM Mono',monospace;font-size:12px;color:var(--ink);}}

  .empty{{text-align:center;padding:70px 20px;color:var(--ink-faint);font-family:'Shippori Mincho',serif;font-size:15px;}}
  footer{{padding:34px 20px 0;text-align:center;color:var(--ink-faint);font-size:11px;font-family:'DM Mono',monospace;}}

  @media (max-width: 480px){{
    .hero h1{{font-size:24px;}}
    table.pred-table{{font-size:12px;}}
    .bar-track{{width:40px;}}
  }}
</style>
</head>
<body>

<div class="hero">
  <div class="wrap">
    <div class="eyebrow">South Kanto NAR AI · Daily Report</div>
    <h1>南関東競馬AI予想</h1>
    <div class="updated">{date} 分 · 最終更新: {generated_at}</div>
    <div class="track-nav">{track_nav}</div>
  </div>
</div>

<div class="wrap">
{content}
</div>

<footer>keiba_ai (南関東版) · model_early_urawa · 毎朝GitHub Actionsで自動更新</footer>

</body>
</html>
"""

EMPTY_TEMPLATE = """
<div class="empty">
  <p>この日は南関東4場(大井・船橋・浦和・川崎)の開催がありませんでした。</p>
</div>
"""


def build_race_card_html(race_id: str, track: str, race_num: int, df_race: pd.DataFrame) -> str:
    df_race = df_race.sort_values("rank")
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
        rows_html.append(f"""
        <tr class="{row_class}">
          <td><span class="umaban">{row['馬番']}</span></td>
          <td>{row['horse_name']}{badge}</td>
          <td><div class="bar-cell"><div class="bar-track"><div class="bar-fill" style="width:{min(win_pct*3,100):.0f}%"></div></div><span class="pct">{win_pct:.1f}%</span></div></td>
          <td><div class="bar-cell"><div class="bar-track"><div class="bar-fill" style="width:{top3_pct:.0f}%"></div></div><span class="pct">{top3_pct:.1f}%</span></div></td>
        </tr>""")
    return f"""
    <div class="race-card">
      <div class="race-head">
        <span class="race-title">{race_num}R</span>
        <span class="rnum">race_id: {race_id}</span>
      </div>
      <table class="pred-table">
        <thead><tr><th>馬番</th><th>馬名</th><th>単勝</th><th>複勝</th></tr></thead>
        <tbody>{''.join(rows_html)}</tbody>
      </table>
    </div>"""


def generate_dashboard(date_str: str) -> Path:
    pred_path = SCRAPED_DIR / f"{date_str}_racecards_raw_predictions.csv"
    out_path = DOCS_DIR / "index.html"

    if not pred_path.exists():
        html = HTML_TEMPLATE.format(
            date=date_str,
            generated_at=datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            track_nav="",
            content=EMPTY_TEMPLATE,
        )
        out_path.write_text(html, encoding="utf-8")
        return out_path

    df = pd.read_csv(pred_path)
    tracks = sorted(df["track"].unique())

    track_nav = " ".join(f'<a href="#{t}">{t}</a>' for t in tracks)
    sections = []
    for track in tracks:
        df_track = df[df["track"] == track]
        race_nums = sorted(df_track["race_num"].unique())
        cards = []
        for rn in race_nums:
            df_race = df_track[df_track["race_num"] == rn]
            race_id = str(df_race.iloc[0]["race_id"])
            cards.append(build_race_card_html(race_id, track, rn, df_race))
        sections.append(f"""
        <section class="track-section" id="{track}">
          <h2 class="track-title">{track} <span class="badge">{len(race_nums)}R</span></h2>
          {''.join(cards)}
        </section>""")

    html = HTML_TEMPLATE.format(
        date=date_str,
        generated_at=datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        track_nav=track_nav,
        content="".join(sections),
    )
    out_path.write_text(html, encoding="utf-8")
    return out_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="日次予想ダッシュボードHTML生成")
    parser.add_argument("--date", default=datetime.date.today().isoformat())
    args, _unknown = parser.parse_known_args()

    out = generate_dashboard(args.date)
    print(f"生成: {out}")
