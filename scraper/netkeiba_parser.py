"""
netkeiba(nar.netkeiba.com/race/newspaper.html)の全選択貼り付けテキストを解析する。

1頭分のブロック構造(添付サンプルより実測):
  枠番(無いこともある)
  馬番
  -- (予想印プレースホルダ)
  馬名
  父名
  母名
  (母父名)
  厩舎(地域・調教師名)
  馬主
  生産牧場
  脚質+中N週      例: "差中8週"
  オッズ (人気)    例: "7.9 (4人気)"
  性齢 毛色        例: "牡3 鹿"
  騎手(替プレフィックスあり得る)
  通算成績 or 初騎乗   例: "1-0-0-0"
  斤量
  [過去走ブロック x 最大5、各6行程度]
  全場ダ ...(タブ区切り成績サマリー、無いこともある)
"""
import re


def split_horse_blocks(text: str) -> list[list[str]]:
    """全選択テキストを1頭ずつのブロック(行リスト)に分割する"""
    lines = [l for l in text.replace('\r\n', '\n').split('\n')]

    # 馬番+"--"のペアを見つけてブロック開始位置とする
    # (枠番が付く場合は 枠番\n馬番\n--、付かない場合は 馬番\n--)
    starts = []
    for i in range(len(lines) - 1):
        if re.match(r'^\d{1,2}$', lines[i]) and lines[i + 1].strip() == '--':
            # 直前行も数字なら「枠番+馬番」、そうでなければ「馬番のみ」
            if i > 0 and re.match(r'^\d{1,2}$', lines[i - 1]) and (i - 1) not in [s[0] for s in starts]:
                starts.append((i - 1, True))   # 枠番あり
            else:
                starts.append((i, False))      # 枠番なし

    blocks = []
    for idx, (start, has_waku) in enumerate(starts):
        end = starts[idx + 1][0] if idx + 1 < len(starts) else len(lines)
        blocks.append(lines[start:end])
    return blocks


def parse_horse_block(block: list[str]) -> dict:
    """1頭分のブロックから現在レースの静的特徴量を抽出する"""
    # 枠番/馬番/--の位置を特定
    i = 0
    waku, umaban = None, None
    if re.match(r'^\d{1,2}$', block[0]) and re.match(r'^\d{1,2}$', block[1]) and block[2].strip() == '--':
        waku, umaban = int(block[0]), int(block[1])
        i = 3
    elif re.match(r'^\d{1,2}$', block[0]) and block[1].strip() == '--':
        umaban = int(block[0])
        i = 2
    else:
        return {}

    horse_name = block[i].strip() if i < len(block) else None
    sire = block[i + 1].strip() if i + 1 < len(block) else None
    dam = block[i + 2].strip() if i + 2 < len(block) else None
    # (母父名) の行
    bms = None
    j = i + 3
    if j < len(block):
        m = re.match(r'^\((.+)\)$', block[j].strip())
        if m:
            bms = m.group(1)
    j += 1  # 厩舎
    j += 1  # 馬主
    j += 1  # 生産牧場

    result = {
        'waku': waku, 'umaban': umaban, 'name': horse_name,
        'sire': sire, 'dam': dam, 'broodmare_sire': bms,
    }

    # 残りの行から脚質・オッズ人気・性齢毛色・騎手・通算成績・斤量を正規表現で拾う
    rest_text = '\n'.join(block[j:j + 8])

    m = re.search(r'^(逃|先|差|追)中(\d+)週$', rest_text, re.MULTILINE)
    if m:
        result['running_style'] = m.group(1)
        result['weeks_since_last'] = int(m.group(2))

    m = re.search(r'^([\d.]+)\s*\((\d+)人気\)$', rest_text, re.MULTILINE)
    if m:
        result['odds'] = float(m.group(1))
        result['ninki'] = int(m.group(2))

    m = re.search(r'^(牡|牝|セン)(\d+)\s+(\S+)$', rest_text, re.MULTILINE)
    if m:
        result['sei'] = m.group(1)
        result['rei'] = int(m.group(2))
        result['kegaro'] = m.group(3)

    m = re.search(r'^(替)?(\S+)$', '\n'.join(block[j+3:j+4]), re.MULTILINE)
    # 騎手行は上記のいずれにもマッチしない単独行として現れるため個別に検索
    for line in block[j:j + 8]:
        lm = re.match(r'^(替)?([^\s\d(){}]+)$', line.strip())
        if lm and 'jockey' not in result and line.strip() not in ('初騎乗',):
            # 性齢行・脚質行等を誤って拾わないよう、既知パターンを除外
            if re.match(r'^(逃|先|差|追)中\d+週$', line.strip()):
                continue
            if re.match(r'^(牡|牝|セン)\d+', line.strip()):
                continue
        # 実際の騎手行検出は形式が安定しないため、下のキャリア成績直前行を採用する簡易ロジックに委ねる

    m = re.search(r'^(\d+-\d+-\d+-\d+|初騎乗)$', rest_text, re.MULTILINE)
    if m:
        result['career_record'] = m.group(1)

    m = re.search(r'^(\d{2}\.\d|\d+\.\d)$', rest_text, re.MULTILINE)
    # 斤量は career_record の直後の単独数値行
    lines_after = block[j:j + 10]
    for k, line in enumerate(lines_after):
        if line.strip() in ('初騎乗',) or re.match(r'^\d+-\d+-\d+-\d+$', line.strip()):
            if k + 1 < len(lines_after):
                wm = re.match(r'^(\d+\.\d)$', lines_after[k + 1].strip())
                if wm:
                    result['kinryo'] = float(wm.group(1))
            # 騎手はその1つ前の行であることが多い
            if k - 1 >= 0:
                jm = re.match(r'^(替)?(\S+)$', lines_after[k - 1].strip())
                if jm:
                    result['jockey'] = jm.group(2)
                    result['jockey_change'] = bool(jm.group(1))
            break

    return result


def parse_summary_table(block: list[str]) -> dict:
    """ブロック末尾の「全場ダ / 門別ダ1200m 等」成績サマリー(タブ区切り)を抽出する"""
    summary = {}
    for line in block:
        m = re.match(r'^(\S+)\t(\d+)\t(\d+)\t(\d+)\t(\d+)$', line.strip())
        if m:
            key, w, s2, s3, out = m.groups()
            total = int(w) + int(s2) + int(s3) + int(out)
            summary[key] = {
                'starts': total,
                'winrate': int(w) / total if total else None,
                'top3rate': (int(w) + int(s2) + int(s3)) / total if total else None,
            }
    return summary


def parse_race_card(text: str) -> list[dict]:
    """全選択テキストから出走馬全頭分の情報を抽出する"""
    blocks = split_horse_blocks(text)
    horses = []
    for block in blocks:
        info = parse_horse_block(block)
        if not info:
            continue
        info['summary'] = parse_summary_table(block)
        horses.append(info)
    return horses


if __name__ == '__main__':
    with open('sample.txt', encoding='utf-8') as f:
        text = f.read()
    horses = parse_race_card(text)
    print(f'{len(horses)}頭を検出')
    for h in horses:
        print(h.get('umaban'), h.get('waku'), h.get('name'), h.get('sei'), h.get('rei'),
              h.get('kegaro'), h.get('kinryo'), h.get('jockey'), h.get('ninki'), h.get('odds'),
              h.get('career_record'), h.get('running_style'), h.get('weeks_since_last'))
