"""M6(南関東・試験)の結果づけ: docs/nar_m6_log.json の各レースに、払戻CSV(nar_payouts.csv)の3連単結果を書き込む"""
import json, sys
import pandas as pd

log_path = sys.argv[1] if len(sys.argv) > 1 else "docs/nar_m6_log.json"
pay_path = sys.argv[2] if len(sys.argv) > 2 else "/tmp/nar_payouts.csv"
log = json.load(open(log_path, encoding="utf-8"))
P = pd.read_csv(pay_path, dtype={"race_id": str, "combo": str})
P = P[P["bet_type"] == "3連単"]
res = {r: (c, v) for r, c, v in zip(P["race_id"], P["combo"], P["payout"])}
n = 0
for rid, e in log.items():
    if rid in res and "ret" not in e:
        c, v = res[rid]
        e["result"] = c
        e["ret"] = float(v) if c in set(e.get("tickets", [])) else 0.0
        n += 1
json.dump(log, open(log_path, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
done = [e for e in log.values() if e.get("ok") and "ret" in e]
print(f"結果づけ {n}件 / 買った(合成2.5倍以上) {len(done)}レース 的中{sum(e['ret']>0 for e in done)} 払戻{sum(e['ret'] for e in done):.0f}円 / 投資{30*100*len(done)}円")
