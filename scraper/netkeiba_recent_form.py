"""
netkeiba形式の1頭分ブロックから、直近5走の詳細(日付・競馬場・クラス・距離・
着順・頭数・人気・騎手・斤量・馬体重・上がり3F・着差)を抽出する。

過去走1件分は概ね以下の構造(行の増減があり得るため、アンカー行から
一定範囲内を正規表現でスキャンする方式にしている):

  06/13  東京 10R 3勝映像を見る      <- アンカー行(日付・場・R番号)
  夏至Ｓ                              <- レース名
  定量                                <- 条件
  6 16頭 6番 3人気                   <- 着順 頭数 馬番 人気
  ダ1600 左 稍 1:35.5                <- コース 距離 回り 馬場 タイム
  ゴンサル 55.0 476kg (-2)           <- 騎手 斤量 馬体重(増減)
  前
  35.5 - - 7 8                       <- 通過順(前半)
  後
  35.6                                <- 上がり3F
  M ルヴァレドクール (0.9) 中位詰め   <- ペース 相手馬 着差 コメント
"""
import re

PAST_RACE_ANCHOR = re.compile(r'^(\d{2})/(\d{2})\s+(\S+?)\s+(\d+)R')
RESULT_RE = re.compile(r'^(\d+)\s+(\d+)頭\s+(\d+)番\s+(\d+)人気$')
COURSE_RE = re.compile(r'^(ダ|芝)(\d+)\s*(左|右)?\s*(良|稍重|稍|重|不良|不)\S*\s+(\d+:[\d.]+|[\d.]+)$')
JOCKEY_RE = re.compile(r'^(\S+?)\s+([\d.]+)\s+(\d+)kg\s*\(([+-]?\d+)\)$')
MARGIN_RE = re.compile(r'^[HMS]\s+\(?([^()]*?)\)?\s*\(([+-]?[\d.]+)\)')


def parse_past_races_netkeiba(block: list[str], max_races: int = 5) -> list[dict]:
    """1頭分のブロック(行リスト)から過去走レコードを新しい順に抽出する"""
    anchor_idx = [i for i, l in enumerate(block) if PAST_RACE_ANCHOR.match(l.strip())]
    races = []

    for n, idx in enumerate(anchor_idx[:max_races]):
        end = anchor_idx[n + 1] if n + 1 < len(anchor_idx) else min(idx + 15, len(block))
        window = [l.strip() for l in block[idx:end]]

        m = PAST_RACE_ANCHOR.match(window[0])
        mon, day, track, race_num = m.groups()
        rec = {'date_md': f'{mon}/{day}', 'track': track, 'race_num': int(race_num)}

        for line in window[1:]:
            rm = RESULT_RE.match(line)
            if rm:
                rec['finish'] = rm.group(1)
                rec['headcount'] = int(rm.group(2))
                rec['umaban'] = int(rm.group(3))
                rec['ninki'] = int(rm.group(4))
                continue
            cm = COURSE_RE.match(line)
            if cm:
                rec['surface'] = cm.group(1)
                rec['distance'] = int(cm.group(2))
                rec['baba'] = cm.group(4)
                rec['time'] = cm.group(5)
                continue
            jm = JOCKEY_RE.match(line)
            if jm:
                rec['jockey'] = jm.group(1)
                rec['kinryo'] = float(jm.group(2))
                rec['weight'] = int(jm.group(3))
                rec['weight_change'] = int(jm.group(4))
                continue
            mm = MARGIN_RE.match(line)
            if mm:
                rec['compare_horse'] = mm.group(1).strip()
                rec['margin'] = float(mm.group(2))
                continue

        # 上がり3F: "後"という行の直後にある数値行
        for k, line in enumerate(window):
            if line == '後' and k + 1 < len(window):
                fm = re.match(r'^([\d.]+)$', window[k + 1])
                if fm:
                    rec['last3f'] = float(fm.group(1))
                break

        # 通過順(前半): "前"という行の直後の行は「上がりタイム 通過順x4」の形式。
        # 先頭のタイム(小数点を含む数値)は通過順ではないので除外して解析する。
        for k, line in enumerate(window):
            if line == '前' and k + 1 < len(window):
                tokens = window[k + 1].split()
                # 先頭トークンが "35.5" のような区間タイムなら除外
                if tokens and re.match(r'^[\d.]+$', tokens[0]) and '.' in tokens[0]:
                    tokens = tokens[1:]
                positions = [int(t) for t in tokens if re.match(r'^\d+$', t)]
                if positions:
                    rec['corner_first'] = positions[0]
                    rec['corner_last'] = positions[-1]
                break

        races.append(rec)

    return races


def build_recent_form_features(races: list[dict]) -> dict:
    """過去走レコードのリストから、モデル入力用の直近5走集計特徴量を作る"""
    if not races:
        return {}

    def avg(key):
        vals = [r[key] for r in races if key in r]
        return sum(vals) / len(vals) if vals else None

    out = {
        'last_ninki': races[0].get('ninki'),
        'avg5_ninki': avg('ninki'),
        'last_margin': races[0].get('margin'),
        'avg5_margin': avg('margin'),
        'avg5_last3f': avg('last3f'),
        'avg5_headcount': avg('headcount'),
        'n_past_races': len(races),
        'avg5_corner_first': avg('corner_first'),
        'avg5_corner_last': avg('corner_last'),
    }
    if 'corner_first' in races[0] and 'corner_last' in races[0]:
        gains = [r['corner_first'] - r['corner_last'] for r in races
                  if 'corner_first' in r and 'corner_last' in r]
        out['avg5_corner_gain'] = sum(gains) / len(gains) if gains else None
    else:
        out['avg5_corner_gain'] = None
    return out


if __name__ == '__main__':
    from netkeiba_parser import split_horse_blocks

    with open('../../netkeiba_test/sample.txt', encoding='utf-8') as f:
        text = f.read()
    blocks = split_horse_blocks(text)
    for block in blocks:
        name = block[3] if block[2].strip() == '--' else block[2]
        races = parse_past_races_netkeiba(block)
        feats = build_recent_form_features(races)
        print(name, '過去走数:', len(races))
        for r in races:
            print('  ', r)
        print('  集計:', feats)
