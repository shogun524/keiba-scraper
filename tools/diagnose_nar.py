"""
nar.netkeiba の取得状況を診断する(過去結果のバックフィル・オッズ記録を作るための下調べ)。

- レース一覧(race_list_sub.html)に race_id が入っているか
- 結果ページ(result.html)の結果表・払戻表の形
- オッズページを開いたときに裏で呼ばれているAPIのURLと応答(単勝・馬連・ワイド)
を diag/ に保存する。

使い方:
    python tools/diagnose_nar.py --dates 20231115 20261109 --results 202344111501 --odds 202645110912 --out diag
"""
import argparse
import json
import os
import re

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dates", nargs="*", default=[])
    ap.add_argument("--results", nargs="*", default=[])
    ap.add_argument("--odds", nargs="*", default=[])
    ap.add_argument("--out", default="diag")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    from playwright.sync_api import sync_playwright
    lines = []

    def log(s):
        print(s, flush=True)
        lines.append(s)

    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = b.new_context(user_agent=UA)
        page = ctx.new_page()
        for d in a.dates:
            for name in ("race_list_sub", "race_list"):
                url = f"https://nar.netkeiba.com/top/{name}.html?kaisai_date={d}"
                try:
                    r = page.goto(url, timeout=40000, wait_until="load")
                    page.wait_for_timeout(2500)
                    html = page.content()
                    ids = sorted(set(re.findall(r"race_id=(\d{12})", html)))
                    log(f"[list {d} {name}] status={r.status if r else None} len={len(html)} race_id={len(ids)} {ids[:4]}")
                    open(f"{a.out}/list_{d}_{name}.html", "w", encoding="utf-8").write(html)
                except Exception as e:
                    log(f"[list {d} {name}] ERROR {e}")
        for rid in a.results:
            url = f"https://nar.netkeiba.com/race/result.html?race_id={rid}"
            try:
                r = page.goto(url, timeout=40000, wait_until="load")
                page.wait_for_timeout(2000)
                html = page.content()
                log(f"[result {rid}] status={r.status if r else None} title={page.title()!r} len={len(html)} "
                    f"Payout={'Payout_Detail_Table' in html} 着順={'着順' in html}")
                open(f"{a.out}/result_{rid}.html", "w", encoding="utf-8").write(html)
            except Exception as e:
                log(f"[result {rid}] ERROR {e}")
        for rid in a.odds:
            for t in ("b1", "b4", "b5"):
                calls = []

                def on_resp(resp):
                    if "api" in resp.url or "odds" in resp.url.lower():
                        try:
                            body = resp.text()[:3000]
                        except Exception:
                            body = ""
                        calls.append({"url": resp.url, "status": resp.status, "body": body})
                page.on("response", on_resp)
                url = f"https://nar.netkeiba.com/odds/index.html?type={t}&race_id={rid}"
                try:
                    page.goto(url, timeout=40000, wait_until="load")
                    page.wait_for_timeout(4000)
                    html = page.content()
                    open(f"{a.out}/odds_{rid}_{t}.html", "w", encoding="utf-8").write(html)
                    log(f"[odds {rid} {t}] page len={len(html)} api_calls={len(calls)}")
                    for c in calls:
                        log(f"    {c['status']} {c['url'][:200]}")
                    json.dump(calls, open(f"{a.out}/odds_{rid}_{t}_calls.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
                except Exception as e:
                    log(f"[odds {rid} {t}] ERROR {e}")
                page.remove_listener("response", on_resp)
            # shutuba (馬体重の有無確認)
            try:
                page.goto(f"https://nar.netkeiba.com/race/shutuba.html?race_id={rid}", timeout=40000, wait_until="load")
                page.wait_for_timeout(2000)
                html = page.content()
                open(f"{a.out}/shutuba_{rid}.html", "w", encoding="utf-8").write(html)
                log(f"[shutuba {rid}] len={len(html)} 馬体重={'馬体重' in html}")
            except Exception as e:
                log(f"[shutuba {rid}] ERROR {e}")
        b.close()
    open(f"{a.out}/summary.txt", "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
