"""
地方競馬: JRA版と同じ仕組みの追加情報(込%・◎の一言・推し・3連複・AI買い目)。

  込%   … オッズ込みの1着率(nar_market_model.py。単勝オッズ + AIの要素の条件付きロジット)
  ◎    … AI(v3。オッズを使わない実力評価)の1着率1位。込%とは別
  一言  … ◎ と 込%1位 が同じか、◎ の人気で決める(下の検証)
  推し  … ◎ が「注意/危険」のレースで代わりに推す馬 = 込%1位
  3連複 … 込%1位を軸 → 込%2〜4位 → AIの3着内率10%以上(E)。そのうち込%の組の確率が市場の1.2倍以上の組(E')

検証(2025〜2026年の約2万5千レース。AIも込%モデルもその前のデータだけで学習):
  ◎=込%1位(1〜2番人気)        実際の勝率/オッズの見込み 1.01倍  単回81% 複回88〜91%      → 普通
  ◎≠込%1位・◎が2〜3番人気      0.95〜1.08倍                                              → 普通
  ◎≠込%1位・◎が1番人気         0.91倍  単回74%                                          → 注意
  ◎≠込%1位・◎が4〜5番人気      0.96倍  ◎の勝率9.5%                                      → 注意
  ◎≠込%1位・◎が6番人気以下     0.86倍  単回67%                                          → 危険
  注意/危険 のときの推し(込%1位) 勝率31〜34%・複勝圏66%・単回82〜88%・複回89〜90%
  3連複 E   平均16.6点・的中率67%・回収率77%(年ごと77%)
  3連複 E'  平均4.8点・的中率16%・回収率90%(年ごと87〜93%)
  ※ 地方は市場(オッズ)がよく当たっていて、JRAの「狙い目!」にあたる、オッズより明らかに来る形は見つからなかった。
"""
import itertools
import json
import os

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
MM_PATH = os.path.join(os.path.dirname(HERE), "model", "nar_market_model.json")
TOP3_MIN = 0.10
EDGE = 1.2
_SPEC = None
TRI = {}          # race_id -> {"1-2-3": 3連単オッズ}(generate_dashboard が最新オッズから入れる)
# 3連単(11/16): 2025〜2026年 約2万3千レースの実際の3連単最終オッズ(人気上位300組)。全レース買う形はどれも100%未満だが、
#   印のフォーメーション × レース条件(万馬券率・頭数・◎の妙味など)では、偶然版(条件をシャッフル)より明らかに多く100%超えが残った → tri_bets
#   ※ 取れたオッズの合計(Σ1/オッズ)が1.1未満のレースは表が欠けているので使わない
TRI_MIN_INV = 1.1

TAGS = {"普通": ("普通", "tg-ok"), "注意": ("注意", "tg-warn"), "危険": ("危険！", "tg-ng"), "推し": ("推し", "tg-push")}

# AI買い目(地方。2025〜26年の検証。3連複E'はほぼ毎レース出るので各レースの欄だけに出す。どれも100%は超えないので、全体の平均(単勝69%・3連複75%前後)よりましな買い方)
RULES = [
    dict(id="N2", name="単勝 込%1位(2番人気で◎と違う)", bet="単勝", sel="込%",
         roi="回収率91%(年ごと90〜92%)・勝率30%",
         desc="込%1位が2番人気で、AIの◎と違う馬のとき、その込%1位の単勝"),
    dict(id="B1", name="3連単 ◎○▲△BOX(24点)", bet="3連単", sel="AI・万馬券率",
         roi="南関東以外 回収率136〜141%・的中率31〜34%",
         desc="南関東以外・8頭立て以下で、3連単の万馬券率(オッズ100倍以上の組の割合)が20〜30%のレース"),
    dict(id="B4", name="3連単 ◎○▲△BOX(24点)", bet="3連単", sel="AI・込%・万馬券率",
         roi="南関東以外 回収率133〜168%・的中率30%", desc="南関東以外・込%1位の1着率45〜60%で、万馬券率20〜30%のレース"),
    dict(id="B7", name="3連単 ◎○▲△BOX(24点)", bet="3連単", sel="AI・万馬券率",
         roi="南関東以外 回収率124〜149%・的中率27%", desc="南関東以外・万馬券率20〜30%で、◎の妙味(込%÷市場)が0.9〜1.0のレース"),
    dict(id="B9", name="3連単 △☆→◎○→◎○▲(8点)", bet="3連単", sel="AI・万馬券率",
         roi="南関東以外 回収率127〜130%・的中率6.5%", desc="南関東以外・8頭立て以下で、万馬券率30〜40%のレース(穴頭)"),
    dict(id="M6", name="3連単 込%1位→3着内率上位6頭(30点・南関東・試験)", bet="3連単", sel="込%・AI3着内率・合成オッズ",
         roi="南関東 回収率104〜132%・的中率28〜37%(年80〜95レース・試験中)",
         desc="南関東で込%1位の1着率が50%以上、かつ30点の合成オッズが2.5倍以上のときだけ(強い本命なのにその馬1着の3連単が安くないレース)"),
    dict(id="M4", name="3連単 ○▲→無印(AI6〜8位)→△☆(12点・南関東)", bet="3連単", sel="AI・込%",
         roi="南関東 回収率137〜196%・的中率3%", desc="南関東で、込%1位の1着率が25〜35%(混戦)のレース。2着に無印を置く穴狙い"),
    dict(id="M5", name="3連単 全→無印(AI6〜8位)→○(約28点・南関東)", bet="3連単", sel="AI",
         roi="南関東 回収率176〜186%・的中率3.5%(大きい配当頼み)", desc="南関東で、◎と○のAIの1着率の差が5pt未満のレース"),
    dict(id="U1", name="馬単 ○→無印(AI6〜8位)(3点・試験)", bet="馬単", sel="AI",
         roi="南関東以外 回収率112〜118%・的中率5%", desc="南関東以外の9〜10頭立てで、◎のAIの1着率が20〜30%のレース"),
    dict(id="N3", name="複勝 推し", bet="複勝", sel="込%",
         roi="回収率89〜90%・複勝圏66%",
         desc="◎が「注意/危険」のレースで、推し(込%1位)の複勝"),
]

GUIDE = """<details class="guide"><summary>見かた(◎・込%・一言・3連複・AI買い目)</summary>
<ul>
<li><b>◎○▲△</b> … AIの1着率の順。AIはオッズ・人気を使わず、過去の成績・タイム・騎手などだけで評価(地方11場のデータで学習)。1番人気以外も普通に◎になる。</li>
<li><b>込%</b> … オッズ込みの1着率。単勝オッズ(みんなの評価)に、AIが見ている要素のうち市場が織り込み切れていない分を足したもの。オッズが変わると変わる。AIの%はオッズでは変わらない。</li>
<li><b>妙味</b> … 込% ÷ オッズから見た確率。1.15以上を「妙味」とする。</li>
<li><b>一言</b> … 普通=◎が込%1位と同じ、または2〜3番人気(ほぼオッズどおり。普通に買ってよい) / 注意=◎が込%1位と違う1番人気・4〜5番人気 / 危険！=◎が込%1位と違う6番人気以下 / 推し=注意・危険のレースで代わりに推す馬(込%1位。過去 複勝圏66%・複回90%)。</li>
<li><b>3連複</b> … E=込%1位軸→込%2〜4位→3着内率10%以上(的中率67%・回収率77%)。E'=そのうち市場より1.2倍以上来やすい組だけ(的中率16%・回収率90%)。</li>
<li><b>EV</b> … 単勝だけ。込% × 今のオッズ。</li>
<li>地方は市場(オッズ)がよく当たっていて、回収率100%を超える買い方は見つかっていない。AI買い目は「全体の平均(単勝約70%)よりまし」なもの。</li>
</ul></details>"""

GUIDE_CSS = """
  .guide{background:var(--paper-card);border:1px solid var(--line);border-radius:6px;padding:8px 12px;margin:14px 0;font-size:12.5px;}
  .guide summary{cursor:pointer;font-weight:700;}
  .guide ul{margin:6px 0 0;padding-left:18px;line-height:1.8;}
  .tg{display:inline-block;font-size:10.5px;font-weight:700;padding:1px 6px;border-radius:9px;margin-left:4px;vertical-align:1px;white-space:nowrap;}
  .tg-ok{background:#E3F1E6;color:#2E7D46;} .tg-warn{background:#FFF1D6;color:#9A6400;}
  .tg-ng{background:#FBE3E1;color:#B0433A;} .tg-push{background:#E3ECFB;color:#1E5FA8;}
  .mk{font-weight:900;color:var(--red);margin-right:2px;}
  .mm{font-size:11px;color:var(--ink-dim);}
  .xbox{margin-top:12px;padding:10px 12px;border:1px solid var(--line);border-radius:6px;background:var(--paper-card);font-size:12.5px;line-height:1.8;}
  .xbox .h{font-weight:700;font-size:13px;}
  .xbox .sub{font-size:11px;color:var(--ink-dim);}
  .rule-badge{display:inline-block;font-size:10.5px;padding:1px 7px;border-radius:9px;background:#EEE;color:#555;margin-left:4px;}
"""


def _spec():
    global _SPEC
    if _SPEC is None:
        with open(MM_PATH, encoding="utf-8") as f:
            _SPEC = json.load(f)
    return _SPEC


def add_mm(df, odds_col="odds"):
    """予想CSV(全レース) -> mm_win(込%)・mkt_win(オッズから見た確率)・value_ratio を足す。オッズが揃わないレースは空"""
    import sys
    sys.path.insert(0, HERE)
    from nar_market_model import apply_probs
    df = df.copy()
    df["mm_win"], df["mkt_win"] = np.nan, np.nan
    sp = _spec()
    if not any(c.startswith("mf_") for c in df.columns):
        return df
    for rid, g in df.groupby(df["race_id"].astype(str)):
        o = pd.to_numeric(g[odds_col], errors="coerce")
        o = o.where(o >= 1)
        miss = o.isna()
        if len(g) < 2 or miss.sum() > max(1, len(g) * 0.3):
            continue
        if miss.any():
            # 11/16: 一部の馬だけ単勝オッズがまだ無い(0.0表示)と、レース全体の込%が出なかった。
            # 3割以下の欠けなら、AIの1着率から仮のオッズ(0.8÷1着率)を入れて計算する(その馬の込%は推定)
            pw = pd.to_numeric(g["p_win"], errors="coerce").clip(lower=0.005)
            o = o.fillna(0.8 / (pw / pw.sum()))
            df.loc[g.index[miss.values], "mm_est"] = True
        x = pd.DataFrame({f: (g["mf_" + f].values if "mf_" + f in g.columns else np.nan) for f in sp["feats"]}, index=g.index)
        x["race_id"] = rid
        x["umaban"] = pd.to_numeric(g["馬番"], errors="coerce").values
        x["_o"] = o.values
        p, pm = apply_probs(x, sp, odds_col="_o")
        df.loc[g.index, "mm_win"], df.loc[g.index, "mkt_win"] = p, pm
    df["value_ratio"] = df["mm_win"] / df["mkt_win"]
    return df


def _u(g):
    return pd.to_numeric(g["馬番"], errors="coerce").astype(int)


def marks(g):
    """{馬番: 印}  AIの1着率の順に ◎○▲△"""
    o = g.sort_values("p_win", ascending=False)
    return {int(u): m for u, m in zip(pd.to_numeric(o["馬番"], errors="coerce"), "◎○▲△")}


def _has_mm(g):
    return "mm_win" in g.columns and pd.to_numeric(g["mm_win"], errors="coerce").notna().all()


def race_tags(g):
    """{馬番: (表示, css, 対象)}  ◎ の一言と推し"""
    if not _has_mm(g):
        return {}
    um = _u(g)
    odds = pd.to_numeric(g["odds"], errors="coerce")
    pop = dict(zip(um, odds.rank(method="min")))
    n = int(um[g["p_win"].astype(float).idxmax()])
    m1 = int(um[pd.to_numeric(g["mm_win"]).idxmax()])
    p = pop.get(n, 99)
    if n == m1 or 2 <= p <= 3:
        return {n: (*TAGS["普通"], "◎")}
    out = {n: (*TAGS["危険" if p >= 6 else "注意"], "◎")}
    out[m1] = (*TAGS["推し"], "推し")
    return out


def _harville_trio(q):
    d = {}
    for a, b, c in itertools.permutations(q, 3):
        qa, qb = q[a], q[b]
        if qa >= 1 or qa + qb >= 1:
            continue
        k = tuple(sorted((a, b, c)))
        d[k] = d.get(k, 0) + qa * qb / (1 - qa) * q[c] / (1 - qa - qb)
    return d


def trio_plan(g):
    if not _has_mm(g) or len(g) < 6:
        return None
    um = _u(g).tolist()
    mm = pd.to_numeric(g["mm_win"]).values
    mk = pd.to_numeric(g["mkt_win"]).values
    pm = dict(zip(um, mm / mm.sum()))
    qm = dict(zip(um, mk / mk.sum()))
    order = sorted(um, key=lambda u: -pm[u])
    axis, second = order[0], order[1:4]
    t3 = dict(zip(um, pd.to_numeric(g["p_top3"], errors="coerce").fillna(0)))
    third = [u for u in order if t3[u] >= TOP3_MIN]
    T = {tuple(sorted((axis, b, c))) for b in second for c in third if len({axis, b, c}) == 3}
    if not T:
        return None
    hm, hq = _harville_trio(pm), _harville_trio(qm)
    tickets = sorted(((t, hm.get(t, 0) / hq[t] if hq.get(t) else 0) for t in T), key=lambda x: -x[1])
    return dict(axis=axis, second=second, third=third, tickets=tickets, edge=[t for t, r in tickets if r >= EDGE])


def fmt_t(t):
    return "-".join(map(str, t))


def race_bets(g):
    """1レースの AI買い目 -> [(ルールid, 買い目の文字列)]"""
    out = []
    if not _has_mm(g):
        return out
    um = _u(g)
    odds = pd.to_numeric(g["odds"], errors="coerce")
    pop = dict(zip(um, odds.rank(method="min")))
    n = int(um[g["p_win"].astype(float).idxmax()])
    i1 = pd.to_numeric(g["mm_win"]).idxmax()
    m1 = int(um[i1])
    if m1 != n and pop.get(m1) == 2:
        out.append(("N2", f"単勝 {m1}番 {g.loc[i1, 'horse_name']}"))
    tags = race_tags(g)
    if m1 in tags and tags[m1][2] == "推し":
        out.append(("N3", f"複勝 {m1}番 {g.loc[i1, 'horse_name']}"))
    out += tri_bets(g)
    # U1(11/16・試験): 南関東以外・9〜10頭・◎のAI1着率20〜30% → 馬単 ○ → 無印(AI6〜8位)(3点)
    #   2025年1558レース 回収率118%・2026年1380レース 112%(的中率5%、大きい配当3本を除いても84〜85%)。
    #   ただ「9〜10頭だけ」「◎20〜30%だけ」では73〜83%で、組み合わせのときだけ良い形なので試験扱い
    rid = str(g["race_id"].iloc[0])
    if rid[4:6] not in ("42", "43", "44", "45") and 9 <= len(g) <= 10:
        ai = pd.to_numeric(g["p_win"], errors="coerce")
        if not ai.isna().any() and 0.2 <= ai.max() / ai.sum() < 0.3:
            order = [int(um[i]) for i in ai.sort_values(ascending=False).index]
            out.append(("U1", f"馬単 {order[1]} → {','.join(map(str, order[5:8]))}(3点)"))
    return out


def tri_bets(g):
    """3連単の推奨(B1/B4/B7/B9/B8 のうち当てはまる最初の1つ)。
    2025〜2026年の実際の3連単オッズで、条件をシャッフルした「偶然版」(両年110%以上 0個)と比べて残った形(本物 8個)。
    条件は確定オッズで測ったもの。締切前のオッズでは条件の当てはまりが少し変わる"""
    rid = str(g["race_id"].iloc[0])
    tri = TRI.get(rid) or {}
    inv = sum(1 / v for v in tri.values() if v)
    if rid[4:6] in ("42", "43", "44", "45"):
        return minami_bets(g, tri)
    if not tri or inv < TRI_MIN_INV or len(g) < 6:
        return []
    # 11/16: B1/B4/B7/B9 は南関東(浦和・船橋・大井・川崎)以外でだけ効いた(南関東では回収率14〜48%)
    man = sum(1 / v for v in tri.values() if v and v >= 100) / inv
    um = _u(g)
    ai = pd.to_numeric(g["p_win"], errors="coerce")
    order = [int(um[i]) for i in ai.sort_values(ascending=False).index]
    a = ai.sort_values(ascending=False).values / ai.sum()
    h = order[0]
    hi = ai.idxmax()
    vr = float(g.loc[hi, "mm_win"] / g.loc[hi, "mkt_win"]) if g.loc[hi, "mkt_win"] else 1
    q1 = float(pd.to_numeric(g["mm_win"]).max() / pd.to_numeric(g["mm_win"]).sum())
    n = len(g)
    m4 = order[:4]
    box = [f"{x}-{y}-{z}" for x in m4 for y in m4 for z in m4 if len({x, y, z}) == 3]
    ura = [f"{x}-{y}-{z}" for x in order[3:5] for y in order[:2] for z in order[:3] if len({x, y, z}) == 3]
    cands = [("B1", box, 0.2 <= man < 0.3 and n <= 8), ("B4", box, 0.45 <= q1 < 0.6 and 0.2 <= man < 0.3),
             ("B7", box, 0.2 <= man < 0.3 and 0.9 <= vr < 1.0), ("B9", ura, 0.3 <= man < 0.4 and n <= 8)]
    # (B8 は南関東以外では2025年99%・2026年125%、南関東では151%・67%とぶれるので外した)
    for key, tks, ok in cands:
        if not ok:
            continue
        od = [tri.get(t) for t in tks]
        known = [o for o in od if o]
        cp = 1 / sum(1 / o for o in known) if known else None
        if cp and cp >= 2:
            form = (f"{','.join(map(str, m4))} BOX" if key in ("B1", "B4", "B7")
                    else f"{','.join(map(str, order[3:5]))} → {','.join(map(str, order[:2]))} → {','.join(map(str, order[:3]))}")
            return [(key, f"3連単 {form}({len(tks)}点・合成{cp:.1f}倍・万馬券率{man:.0%})")]
    return []


M6_COMP = 2.5
M6_SEEN = {}      # race_id -> 判定の中身(ログ用)
M6_SUMMARY = None  # 試験成績(generate_dashboard がログから入れる)


def log_m6(df, path, now=None):
    """M6 の判定を docs/nar_m6_log.json に残す。発走前のレースだけ上書きし、発走後は最後の判定で固定(=実際に買えた判定)"""
    import datetime as _dt
    now = now or _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=9))).replace(tzinfo=None)
    try:
        log = json.load(open(path, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        log = {}
    for rid, g in df.groupby(df["race_id"].astype(str)):
        if rid[4:6] not in ("42", "43", "44", "45") or rid not in M6_SEEN:
            continue
        h = g.iloc[0]
        try:
            post = _dt.datetime.strptime(f'{h["date"]} {h["post_time"]}', "%Y-%m-%d %H:%M")
        except Exception:  # noqa: BLE001
            continue
        if now >= post:
            continue
        e = dict(M6_SEEN[rid]); e.update(date=str(h["date"]), track=str(h["track"]), R=int(h["race_num"]),
                                         post=str(h["post_time"]), ts=now.strftime("%H:%M"))
        log[rid] = e
    json.dump(log, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    return log



def _m6(g, tri, um):
    """M6(11/20・試験): 南関東・込%1位の1着率50%以上 → 込%1位を1着固定、2・3着にAIの3着内率の上位6頭(30点)。
    30点の合成オッズが2.5倍以上のときだけ買う。2025〜26年の確定オッズで 2025年104%(95R)・2026年132%(81R)。
    合成の下限を上げるほど両年とも上がる(2.0倍 82/97% → 3.0倍 140/199%)。最大配当1本を除くと88/102%。大井・船橋◎、浦和×。
    ※ 3連単オッズの表が欠けている(Σ1/オッズ<1.1)と合成が高く出てしまうので使わない"""
    inv = sum(1 / v for v in tri.values() if v)
    mm = pd.to_numeric(g["mm_win"], errors="coerce")
    t3 = pd.to_numeric(g.get("p_top3"), errors="coerce") if "p_top3" in g else None
    if not tri or inv < TRI_MIN_INV or mm.isna().all() or t3 is None or t3.isna().all() or len(g) < 7:
        return []
    q1 = float(mm.max() / mm.sum())
    if q1 < 0.5:
        return []
    head = int(um[mm.idxmax()])
    sub = [int(um[i]) for i in t3.sort_values(ascending=False).index if int(um[i]) != head][:6]
    tks = [f"{head}-{b}-{c}" for b in sub for c in sub if b != c]
    cp = 1 / sum(1 / (tri.get(t) or 1000.0) for t in tks)
    M6_SEEN[str(g["race_id"].iloc[0])] = dict(cp=round(cp, 2), q1=round(q1, 3), head=head, sub=sub, ok=cp >= M6_COMP, tickets=tks)
    if cp < M6_COMP:
        return []
    return [("M6", f"3連単 {head} → {','.join(map(str, sub))} → {','.join(map(str, sub))}(30点・合成{cp:.1f}倍・込1位{q1:.0%})")]


def minami_bets(g, tri):
    """南関東用の3連単(11/16): 無印(AIの6位以下)を2着に入れる形。南関東だけで、無印を含む形 × 条件を総当たりし、
    偶然版(条件をシャッフル)より多く残った中から点数が少なめで大きい配当を除いても崩れにくいもの
      M4 込%1位の1着率25〜35%: ○▲ → AI6〜8位 → △☆(12点)  2025年137%・2026年196%(的中率3%・大きい配当3本を除くと71〜85%)
      M5 ◎と○のAIの1着率の差5pt未満: 全 → AI6〜8位 → ○(約28点)  2025年186%・2026年176%(的中率3.5%・除くと46〜66%)"""
    um = _u(g)
    ai = pd.to_numeric(g["p_win"], errors="coerce")
    if len(g) < 8 or ai.isna().any():
        return []
    order = [int(um[i]) for i in ai.sort_values(ascending=False).index]
    a = ai.sort_values(ascending=False).values / ai.sum()
    q1 = float(pd.to_numeric(g["mm_win"]).max() / pd.to_numeric(g["mm_win"]).sum())
    F = lambda A, B, C: [f"{x}-{y}-{z}" for x in A for y in B for z in C if len({x, y, z}) == 3]  # noqa: E731
    cands = [("M4", F(order[1:3], order[5:8], order[3:5]), 0.25 <= q1 < 0.35,
              f"{','.join(map(str, order[1:3]))} → {','.join(map(str, order[5:8]))} → {','.join(map(str, order[3:5]))}"),
             ("M5", F(order, order[5:8], order[1:2]), a[0] - a[1] < 0.05,
              f"全 → {','.join(map(str, order[5:8]))} → {order[1]}")]
    m6 = _m6(g, tri, um)
    if m6:
        return m6
    for key, tks, ok, form in cands:
        if not ok:
            continue
        known = [tri.get(t) for t in tks if tri.get(t)]
        cp = 1 / sum(1 / o for o in known) if known else None
        if cp is not None and cp < 2:
            continue
        return [(key, f"3連単 {form}({len(tks)}点{'・合成' + format(cp, '.1f') + '倍' if cp else ''})")]
    return []


def tag_html(t):
    return f'<span class="tg {t[1]}">{t[0]}</span>' if t else ""


def race_box_html(g):
    """レースページ用: 一言・推し・3連複・AI買い目・単勝EV"""
    if not _has_mm(g):
        return ('<div class="xbox"><span class="sub">オッズが出ると、込%・一言・3連複・AI買い目が出ます'
                '(締切前に10分おき更新)。</span></div>')
    um = _u(g)
    tags = race_tags(g)
    name = dict(zip(um, g["horse_name"]))
    lines = []
    for u, t in tags.items():
        lab = "◎" if t[2] == "◎" else "推し"
        lines.append(f'{lab} {u}番 {name.get(u, "")}{tag_html(t)}')
    tp = trio_plan(g)
    if tp:
        e = f'{tp["axis"]} - {",".join(map(str, tp["second"]))} - {",".join(map(str, tp["third"]))}({len(tp["tickets"])}点)'
        ed = " / ".join(fmt_t(t) for t in tp["edge"]) or "なし"
        lines.append(f'<b>3連複 E</b> {e} <span class="sub">的中率67%・回収率77%</span>')
        ne = f"({len(tp['edge'])}点)" if tp["edge"] else ""
        lines.append(f"<b>3連複 E'</b> {ed}{ne} " + '<span class="sub">的中率16%・回収率90%</span>')
    bets = race_bets(g)
    rmeta = {r["id"]: r for r in RULES}
    if bets:
        lines.append("<b>AI買い目</b> " + " ・ ".join(f'{b}<span class="rule-badge">{rmeta[i]["name"]}</span>' for i, b in bets))
    odds = pd.to_numeric(g["odds"], errors="coerce")
    ev = (pd.to_numeric(g["mm_win"]) * odds).values
    top = sorted(zip(um, ev, odds), key=lambda x: -x[1])[:3]
    lines.append("<b>単勝EV</b> " + " ・ ".join(
        f'{u}番 {o:.1f}倍 <span style="color:{"#2E7D46" if e >= 1 else "#9A9A9A"};font-weight:700;">EV {e:.2f}</span>' for u, e, o in top)
        + ' <span class="sub">(込% × オッズ)</span>')
    return GUIDE + '<div class="xbox"><div class="h">一言・3連複・AI買い目</div>' + "<br>".join(lines) + "</div>"


def home_bets_html(df):
    """ホーム用: 今日の AI買い目(ルールごと)"""
    meta = {r["id"]: r for r in RULES}
    by = {r["id"]: [] for r in RULES}
    for rid, g in df.groupby(df["race_id"].astype(str)):
        h = g.iloc[0]
        for i, b in race_bets(g):
            by[i].append(f'<li><a href="races/{h["track"]}_{int(h["race_num"])}.html">{h["track"]}{int(h["race_num"])}R</a> '
                         f'{h.get("post_time") or ""} ・ {b}</li>')
    secs = ""
    for i, items in by.items():
        r = meta[i]
        body = f'<ul style="font-size:12.5px;line-height:1.9;padding-left:18px;margin:4px 0;">{"".join(items)}</ul>' if items \
            else '<div class="sub" style="margin:2px 0 6px;">今日は対象なし(オッズが出たレースから判定)</div>'
        if i == "M6" and M6_SUMMARY:
            sm = M6_SUMMARY
            body = (f'<div class="sub" style="margin:2px 0;">試験の実績(11/21〜・締切前の最後の判定で買った場合): '
                    f'{sm["races"]}レース・的中{sm["hits"]}・回収率{sm["roi"]:.0%}</div>') + body
        secs += (f'<div style="margin-top:8px;"><b>{r["name"]}</b><span class="rule-badge">選ぶのは{r["sel"]}</span>'
                 f'<span class="rule-badge">{r["roi"]}</span><div class="sub">{r["desc"]}</div>{body}</div>')
    return (f'<section class="track-block"><div class="track-block-head"><h2>AI買い目</h2>'
            f'<span style="font-size:11px;color:var(--ink-dim);">2025〜26年の検証で全体の平均よりましな買い方</span></div>'
            f'{GUIDE}<div class="xbox">{secs}</div></section>')
