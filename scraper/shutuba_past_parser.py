"""
netkeiba shutuba_past.html (https://nar.netkeiba.com/race/shutuba_past.html?race_id=XXX) の
全選択貼り付けテキストを解析する。

newspaper.html と違い、プレミアム会員でなくても全頭分の直近5走詳細が取得できる。

1頭分のブロック構造(実測):
  枠番\t馬番\t
  --
  父名
  馬名
  母名
  (母父名)
  厩舎(地域・調教師名)
  脚質+中N週      例: "差中2週"
  (半角スペース)オッズ (人気)   例: " 42.3 (7人気)"
  性齢毛色(スペース無し結合)    例: "牝4鹿"
  騎手
  斤量\t

  [過去走 x 最大5、各7行]
  YYYY.MM.DD 場+R番号(またはR番号の代わりに"取"=競走除外)
  クラス
  芝orダ距離 タイム 馬場状態
  頭数 馬番 人気 騎手 斤量
  通過順 (上がり3F) 馬体重(増減)
  相手馬(着差)
  映像を見る
"""
import re

HORSE_ANCHOR = re.compile(r'^(\d{1,2})\t(\d{1,2})\t?$')
PAST_RACE_ANCHOR = re.compile(r'^(\d{4})\.(\d{2})\.(\d{2})\s+(\S+)$')
RACE_NUM_LINE = re.compile(r'^(\d+|取)$')
RESULT_LINE = re.compile(r'^(\d+)頭\s+(\d+)番\s+(\d+)人\s+(\S+)\s+([\d.]+)$')
COURSE_LINE = re.compile(r'^(ダ|芝)(\d+)(?:\s+(\d+:[\d.]+|[\d.]+))?\s*(良|稍重|稍|重|不良|不)?$')
CORNER_LINE = re.compile(r'^([\d\-]+)?\s*\(([\d.]+)\)\s*(\d+)?\(([+-]?\d+)\)?$')
MARGIN_LINE = re.compile(r'^(\S+?)\(([+-]?[\d.]+)\)$')


def _filter_blank(lines: list[str]) -> list[str]:
    """空行・タブのみの行を除去する(Playwrightの描画で挿入される空要素対策)。
    ただし馬ブロックの区切りに使う空行(2頭の間の完全な空行)は元々1個だけなので、
    ここで全部除去しても情報は失われない。"""
    return [l for l in lines if l.strip() != '']


def split_horse_blocks(text: str) -> list[list[str]]:
    """全選択テキストを1頭ずつのブロック(行リスト)に分割する。
    空行は先に全て除去する(Playwrightのレンダリングで挿入される空要素対策)。"""
    lines = _filter_blank(text.replace('\r\n', '\n').split('\n'))
    starts = []
    for i in range(len(lines) - 1):
        if HORSE_ANCHOR.match(lines[i]) and lines[i + 1].strip() == '--':
            starts.append(i)
    blocks = []
    for idx, start in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(lines)
        blocks.append(lines[start:end])
    return blocks


def parse_horse_static(block: list[str]) -> dict:
    """1頭分のブロックから現在レースの静的特徴量を抽出する"""
    m = HORSE_ANCHOR.match(block[0])
    if not m:
        return {}
    waku, umaban = int(m.group(1)), int(m.group(2))

    if len(block) < 12:
        return {'waku': waku, 'umaban': umaban}

    sire = block[2].strip()
    name = block[3].strip()
    dam = block[4].strip()
    bms_m = re.match(r'^\((.+)\)$', block[5].strip())
    bms = bms_m.group(1) if bms_m else None

    result = {
        'waku': waku, 'umaban': umaban, 'name': name,
        'sire': sire, 'dam': dam, 'broodmare_sire': bms,
    }

    # 6行目以降、脚質・オッズ・性齢毛色・騎手・斤量を順に走査。
    # 過去走の最初のアンカー(日付行)が来るまでを走査範囲とする(空行除去で
    # 行数が変動するため固定オフセットではなく動的に決める)。
    idx = 6
    scan_end = len(block)
    for i in range(idx, len(block)):
        if PAST_RACE_ANCHOR.match(block[i].strip()):
            scan_end = i
            break
    for i in range(idx, scan_end):
        line = block[i].strip()
        rs_combined = re.match(r'^(逃|先|差|追)中(\d+)週$', line)
        if rs_combined:
            result['running_style'] = rs_combined.group(1)
            result['weeks_since_last'] = int(rs_combined.group(2))
            continue
        rs_style_only = re.match(r'^(逃|先|差|追)$', line)
        if rs_style_only and i + 1 < scan_end:
            weeks_m = re.match(r'^中(\d+)週$', block[i + 1].strip())
            if weeks_m:
                result['running_style'] = rs_style_only.group(1)
                result['weeks_since_last'] = int(weeks_m.group(1))
                continue
        odds_m = re.match(r'^([\d.]+)\s*\((\d+)人気\)$', line)
        if odds_m:
            result['odds'] = float(odds_m.group(1))
            result['ninki'] = int(odds_m.group(2))
            continue
        sac_m = re.match(r'^(牡|牝|セン)(\d+)(\S+)$', line)
        if sac_m:
            result['sei'] = sac_m.group(1)
            result['rei'] = int(sac_m.group(2))
            result['kegaro'] = sac_m.group(3)
            continue
        kinryo_m = re.match(r'^([\d.]+)$', line)
        if kinryo_m and 'kinryo' not in result and 'sei' in result:
            result['kinryo'] = float(kinryo_m.group(1))
            continue
        if 'sei' in result and 'kinryo' not in result and 'jockey' not in result \
                and not re.match(r'^[\d.]+$', line) and line:
            result['jockey'] = line

    return result


def parse_past_races(block: list[str], max_races: int = 5) -> list[dict]:
    """1頭分のブロックから過去走レコードを新しい順に抽出する"""
    anchor_positions = []
    for i, line in enumerate(block):
        m = PAST_RACE_ANCHOR.match(line.strip())
        if m:
            anchor_positions.append((i, m))

    races = []
    for n, (idx, m) in enumerate(anchor_positions[:max_races]):
        end = anchor_positions[n + 1][0] if n + 1 < len(anchor_positions) else min(idx + 9, len(block))
        window = [l.strip() for l in block[idx:end]]

        yyyy, mm, dd, track = m.groups()
        rec = {'date': f'{yyyy}-{mm}-{dd}', 'track': track, 'scratched': False}

        # レース番号は次の行に単独で来る(取消の場合は"取")
        if len(window) > 1 and RACE_NUM_LINE.match(window[1]):
            rec['scratched'] = window[1] == '取'

        for line in window[1:]:
            cm = COURSE_LINE.match(line)
            if cm:
                rec['surface'] = cm.group(1)
                rec['distance'] = int(cm.group(2))
                if cm.group(3):
                    rec['time'] = cm.group(3)
                if cm.group(4):
                    rec['baba'] = cm.group(4)
                continue
            rm = RESULT_LINE.match(line)
            if rm:
                rec['headcount'] = int(rm.group(1))
                rec['umaban'] = int(rm.group(2))
                rec['ninki'] = int(rm.group(3))
                rec['jockey'] = rm.group(4)
                rec['kinryo'] = float(rm.group(5))
                continue
            crm = CORNER_LINE.match(line)
            if crm:
                if crm.group(1):
                    parts = [int(p) for p in crm.group(1).split('-') if p]
                    if parts:
                        rec['corner_first'] = parts[0]
                        rec['corner_last'] = parts[-1]
                rec['last3f'] = float(crm.group(2))
                if crm.group(3):
                    rec['weight'] = int(crm.group(3))
                if crm.group(4):
                    rec['weight_change'] = int(crm.group(4))
                continue
            mm_ = MARGIN_LINE.match(line)
            if mm_:
                rec['compare_horse'] = mm_.group(1)
                rec['margin'] = float(mm_.group(2))
                continue

        races.append(rec)

    return races


def build_recent_form_features(races: list[dict]) -> dict:
    """過去走レコードのリストから、モデル入力用の直近5走集計特徴量を作る"""
    valid_races = [r for r in races if not r.get('scratched')]
    if not valid_races:
        return {}

    def avg(key):
        vals = [r[key] for r in valid_races if key in r]
        return sum(vals) / len(vals) if vals else None

    out = {
        'last_ninki': valid_races[0].get('ninki'),
        'avg5_ninki': avg('ninki'),
        'last_margin': valid_races[0].get('margin'),
        'avg5_margin': avg('margin'),
        'avg5_last3f': avg('last3f'),
        'avg5_headcount': avg('headcount'),
        'n_past_races': len(valid_races),
        'avg5_corner_first': avg('corner_first'),
        'avg5_corner_last': avg('corner_last'),
        'most_recent_track': valid_races[0].get('track'),
        'most_recent_date': valid_races[0].get('date'),
    }
    gains = [r['corner_first'] - r['corner_last'] for r in valid_races
             if 'corner_first' in r and 'corner_last' in r]
    out['avg5_corner_gain'] = sum(gains) / len(gains) if gains else None
    return out


def parse_race_card(text: str) -> list[dict]:
    """全選択テキストから出走馬全頭分の情報(静的特徴+直近5走集計)を抽出する"""
    blocks = split_horse_blocks(text)
    horses = []
    for block in blocks:
        info = parse_horse_static(block)
        if not info.get('name'):
            continue
        races = parse_past_races(block)
        info['recent_form'] = build_recent_form_features(races)
        info['_races'] = races
        horses.append(info)
    return horses


if __name__ == '__main__':
    with open('sample.txt', encoding='utf-8') as f:
        text = f.read()
    horses = parse_race_card(text)
    print(f'{len(horses)}頭を検出')
    for h in horses:
        print(h['umaban'], h['name'], h.get('sei'), h.get('rei'), h.get('kegaro'),
              h.get('kinryo'), h.get('jockey'), h.get('ninki'), h.get('odds'),
              h.get('running_style'), h.get('weeks_since_last'))
        print('  過去走:', len(h['_races']), '集計:', h['recent_form'])
