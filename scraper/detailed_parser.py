"""
NARサイト形式(出馬表全選択コピペ)から、直近5走の詳細データ(日付・馬場状態・頭数・
競馬場・距離・馬番・人気・馬体重・騎手・斤量・タイム・通過順・上がり3F・着差)を抽出する。

一頭分のブロック構造:
  0: 枠番\t馬番\t馬名\t騎手(所属)\tオッズ
  1: (人気)
  2-6: 全/左/右/場/距 (集計成績)
  7: 最高タイム,馬場
  8..: [着順(or取消/中止)+日付 baba headcount頭] / [場所 [左|右]距離 umaban番] のペア(実際の出走数分、最大5)
  ...: 空行パディング
  N: 性齢\t毛色\t生年月日\t斤量(+騎乗成績)\t[5走分のレース名]
  N+1: 父名\t調教師(所属)\t馬体重
  N+2: (増減)\t[5走分の 人気 体重 騎手 斤量]
  N+3: 母名\t馬主\t[5走分の タイム 通過順 上3F]
  N+4: (母父名)\t生産牧場\t\t[5走分の 着差 1着馬名]
"""
import re


def parse_detailed_past_races(block_lines):
    """一頭分のブロック(行リスト)から直近5走の詳細レコードを抽出する。"""
    # 日付ペア行を探す(着順/取消/中止 + 日付 + 馬場 + 頭数)
    date_pairs = []  # [(finish, date, baba, headcount, track, direction, distance, umaban), ...]
    i = 0
    n = len(block_lines)
    while i < n - 1:
        m1 = re.match(r'^(取消|中止|\d{1,2})(\d{2}\.\d{2}\.\d{2})\u3000(\S+)\u3000(\d+)頭$', block_lines[i])
        if m1:
            m2 = re.match(r'^(\S+?)\u3000(左|右)?(\d+)\u3000(\d+)番$', block_lines[i + 1])
            if m2:
                date_pairs.append({
                    'finish_raw': m1.group(1), 'date_short': m1.group(2),
                    'baba': m1.group(3), 'headcount': int(m1.group(4)),
                    'track': m2.group(1), 'direction': m2.group(2), 'distance': int(m2.group(3)),
                    'umaban': int(m2.group(4)),
                })
                i += 2
                continue
        i += 1
    date_pairs = date_pairs[:5]

    # 性齢行(N行目)を探す
    sei_idx = None
    for idx, line in enumerate(block_lines):
        if re.match(r'^(牡|牝|セン)\d+\t', line):
            sei_idx = idx
            break
    if sei_idx is None or sei_idx + 4 >= len(block_lines):
        return date_pairs, []  # 詳細行が見つからない場合は日付だけ返す

    sei_cells = block_lines[sei_idx].split('\t')
    race_names = sei_cells[4:9]

    bw_line1_cells = block_lines[sei_idx + 1].split('\t')  # 父名, 調教師, 馬体重
    bw_line2_cells = block_lines[sei_idx + 2].split('\t')  # (増減), [5走: 人気 体重 騎手 斤量]
    dam_cells = block_lines[sei_idx + 3].split('\t')       # 母名, 馬主, [5走: タイム 通過順 上3F]
    bms_cells = block_lines[sei_idx + 4].split('\t')       # (母父名), 生産牧場, , [5走: 着差 1着馬名]

    ninki_weight_jockey = bw_line2_cells[1:6]
    time_corner_f3 = dam_cells[2:7]
    margin_winner = bms_cells[3:8]

    races = []
    for k, dp in enumerate(date_pairs):
        rec = dict(dp)
        rec['race_name'] = race_names[k] if k < len(race_names) else ''

        if k < len(ninki_weight_jockey):
            m = re.match(r'(\d+)人\u3000(\d+)\u3000(\S+)\s+([\d.]+)', ninki_weight_jockey[k])
            if m:
                rec['ninki'] = int(m.group(1))
                rec['weight'] = int(m.group(2))
                rec['jockey'] = m.group(3)
                rec['kinryo'] = float(m.group(4))

        if k < len(time_corner_f3):
            m = re.match(r'(\d+:[\d.]+|[\d.]*)\u3000([\d\-]*)\u3000?([\d.]*)', time_corner_f3[k])
            if m:
                rec['time'] = m.group(1) or None
                rec['corners'] = m.group(2) or None
                rec['last3f'] = float(m.group(3)) if m.group(3) else None

        if k < len(margin_winner):
            m = re.match(r'([\d.]*)\u3000?(\S*)', margin_winner[k])
            if m:
                rec['margin'] = float(m.group(1)) if m.group(1) else None
                rec['winner'] = m.group(2) or None

        races.append(rec)
    return date_pairs, races


if __name__ == '__main__':
    text = open('urawa_fullpage.txt', encoding='utf-8').read()
    lines = text.split('\n')
    start = next(i for i, l in enumerate(lines) if l.startswith('1\t1\tサンボールダー'))
    end = next(i for i, l in enumerate(lines) if l.startswith('2\t2\tワンダーダイカネン'))
    block = lines[start:end]
    date_pairs, races = parse_detailed_past_races(block)
    for r in races:
        print(r)
