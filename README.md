# 南関東競馬AI (大井・船橋・浦和・川崎)

2025年南関東4場データで学習したAIモデルと、netkeibaからの自動スクレイピング&予想パイプラインです。

## 構成

```
.
├── model/
│   ├── model_early_urawa_is_win.txt   # 単勝勝率モデル(LightGBM)
│   ├── model_early_urawa_is_top3.txt  # 複勝(3着内)率モデル(LightGBM)
│   └── predict.py                      # スクレイピング済みデータ→予想結果CSV
├── scraper/
│   ├── scraper_netkeiba.py            # 出馬表スクレイパー(Playwright)
│   └── shutuba_past_parser.py         # 出馬表テキストの解析ロジック
├── tools/
│   ├── keiba_ai_predictor.html        # ブラウザ版予想ツール(全場・門別など)
│   └── keiba_ai_predictor_minamikanto.html  # ブラウザ版予想ツール(南関東専用)
├── .github/workflows/
│   └── scrape_and_predict.yml         # 毎日自動実行するActionsワークフロー
└── requirements.txt
```

## データソースについて(重要・必読)

**keiba.go.jp(地方競馬情報サイト)はrobots.txtで自動アクセスを禁止しています。** 対象にしないでください。

**netkeiba(nar.netkeiba.com)は自動アクセスを禁止していません**(2026年8月時点でfetchツールで確認)。
ただし変更される可能性があるため、本番運用前に `https://nar.netkeiba.com/robots.txt` と
利用規約を必ず確認してください。

### なぜ `shutuba_past.html` を使っているか

当初 `race/newspaper.html` を使っていましたが、**5番人気以下の馬は「プレミアムサービス」の
案内に置き換わってしまい、無料では直近の成績データが取得できない**という制限がありました。

`race/shutuba_past.html?race_id=XXX` であれば、**プレミアム会員でなくても全頭分の
直近5走詳細(日付・クラス・距離・タイム・馬場状態・頭数・人気・騎手・斤量・馬体重・
上がり3F・通過順・着差)が取得できます**。そのため、スクレイパーはこちらを対象にしています。

## モデルについて

- 2024年南関東4場データで学習、AUC 0.737(単勝)/ 0.736(複勝)を6週間の完全ホールドアウトで検証
- **馬体重を使いません**(検証の結果、精度への影響がほぼ無かったため)。単勝オッズも使いません。
  そのため、レース前日に出馬表が発表された時点でいつでも予想を実行できます

## セットアップ

```bash
pip install -r requirements.txt
playwright install --with-deps chromium
```

## 使い方(ローカル)

```bash
cd scraper
python scraper_netkeiba.py --date 2026-08-14

cd ../model
python predict.py --input ../scraper/scraped_data/2026-08-14_racecards_raw.jsonl
```

**注意**: Jupyterノートブックのセルに直接貼り付けて実行すると、Playwrightの同期APIが
非同期イベントループと競合してエラーになります。ターミナル/コマンドプロンプトから
`python scraper_netkeiba.py` の形で実行してください。

## GitHub Actionsでの自動化

`.github/workflows/scrape_and_predict.yml` が毎日21:00 JSTに自動実行し、`scraper/scraped_data/`
に生データとCSVを、`docs/index.html` に**貼り付け不要で見られる予想ダッシュボード**をコミットします。
手動実行(Actionsタブ→Run workflow)も可能です。

### ダッシュボードをGitHub Pagesで公開する(推奨)

1. リポジトリの Settings → Pages を開く
2. Source を「Deploy from a branch」、Branch を `main` / `/docs` に設定して保存
3. 数分後、`https://{ユーザー名}.github.io/{リポジトリ名}/` で毎朝自動更新される
   予想一覧が見られるようになります(貼り付け操作は一切不要です)

失敗時は最初のリクエストのスクリーンショットが `debug-screenshots` アーティファクトとして
保存されるので、実行結果ページ下部から確認できます。

## 検証済みの動作(2026年8月時点)

実際の大井1R(2026-08-13)データで検証し、以下を確認済みです:
- 全12頭の直近5走データを正しく抽出(馬名・血統・成績とも取り違えなし)
- 予測確率が的確に分布(単勝1.7%〜30.7%)
- AI予想1位「ペイルムーン」は実オッズでも1番人気(2.5倍)と一致

## 正直な現状・今後の課題

1. **通算成績(career_starts等)は現在未取得**です。`shutuba_past.html`には直近5走はあっても
   通算成績の表示が無いため、この特徴量は常に欠損値として扱われています
   (モデルは欠損値を自動処理するので動作はしますが、以前の学習データにあった情報は使えていません)
2. **レース格・距離の抽出精度**: `predict.py` の `guess_race_meta()` は正規表現による簡易抽出です。
   実際の出力を見て精度を確認してください
3. **「該当レース無し」判定**: 開催していない場・日付へのアクセス時の判定条件は実データで
   検証済みですが、想定外のパターンがあれば `debug-screenshots` を見て調整してください

## 免責

このツールは研究・個人利用目的です。投票の自動化機能は含んでいません(意図的に実装していません)。
予想結果は参考情報であり、投票の最終判断はご自身の責任で行ってください。
