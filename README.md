# 南関東競馬AI (大井・船橋・浦和・川崎)

2024年1〜12月の南関東4場データで学習したAIモデルと、自動化パイプラインの雛形です。

## 構成

```
.
├── model/
│   ├── model_early_urawa_is_win.txt   # 単勝勝率モデル(LightGBM)
│   ├── model_early_urawa_is_top3.txt  # 複勝(3着内)率モデル(LightGBM)
│   ├── features.py                     # 特徴量定義・変換ロジック
│   └── predict.py                      # スクレイピング済みデータ→予想結果CSV
├── scraper/
│   ├── scraper_netkeiba.py            # netkeiba出馬表スクレイパー(Playwright)
│   ├── netkeiba_parser.py             # netkeiba全選択テキストのパーサー
│   └── detailed_parser.py             # (地方競馬情報サイト形式向け・参考用)
├── tools/
│   ├── keiba_ai_predictor.html        # ブラウザ版予想ツール(全場・門別など)
│   └── keiba_ai_predictor_minamikanto.html  # ブラウザ版予想ツール(南関東専用)
├── .github/workflows/
│   └── scrape_and_predict.yml         # 毎日自動実行するActionsワークフロー
└── requirements.txt
```

## モデルについて

- 2024年1〜12月・南関東4場・約27,000件で学習
- 6週間の完全ホールドアウト検証: 単勝AUC 0.737 / 複勝AUC 0.736
- **馬体重を使いません**(検証の結果、精度への影響がほぼ無かったため)。
  単勝オッズも使っていません。そのため、レース前日に出馬表が発表された
  時点でいつでも予想を実行できます。

## データソースについて(重要・必読)

**keiba.go.jp(地方競馬情報サイト)はrobots.txtで自動アクセスを禁止しています。**
このサイトを対象にした自動スクレイピングは行わないでください。

**netkeiba(nar.netkeiba.com)は、少なくとも`race/newspaper.html`について
2026年8月13日時点でrobots.txtによるブロックが確認されませんでした。**
ただし以下を必ず確認してください:
- robots.txtは変更される可能性があるため、運用前に
  `https://nar.netkeiba.com/robots.txt` を直接確認する
- 利用規約(`https://www.netkeiba.com/info/kiyaku.html`)を確認する
- サーバーに負荷をかけないよう、スクレイパーには間隔調整(3〜6秒)を入れています

## セットアップ

```bash
pip install -r requirements.txt
playwright install --with-deps chromium
```

## 使い方(ローカル)

```bash
# 1. 出馬表をスクレイピング(翌日分、南関東4場)
cd scraper
python scraper_netkeiba.py --date 2026-08-14

# 2. 予想を実行
cd ../model
python predict.py --input ../scraper/scraped_data/2026-08-14_racecards_raw.jsonl
```

**注意**: JupyterノートブックでPlaywrightの同期APIを直接実行すると、
非同期ループの競合でエラーになります(Windows環境では`NotImplementedError`)。
必ずターミナル/コマンドプロンプトから `python scraper_netkeiba.py` の形で
実行してください。

## GitHub Actionsでの自動化

`.github/workflows/scrape_and_predict.yml` が毎日21:00 JSTに自動実行し、
結果を `scraper/scraped_data/` にコミットします。手動実行(workflow_dispatch)
も可能です。

## 正直な現状(重要)

このリポジトリは「動く雛形」であり、完成品ではありません。特に以下は
実運用前に確認・改善が必要です:

1. **`netkeiba_parser.py` の精度**: 添付いただいた1レース分のサンプルで
   検証し、7頭中6頭を正しく解析できることを確認していますが(1頭は
   サンプルデータ側の入力漏れ)、サンプル数が少ないため、実際に多数の
   レースでテストして精度を確認してください。
2. **直近5走の詳細特徴量が未接続**: `features.py` の
   `last_ninki` / `avg5_ninki` / `avg5_margin` / `avg5_last3f` /
   `avg5_corner_*` などは、現状すべて欠損値(None)のまま予想しています。
   LightGBMは欠損値を自動処理するため動作はしますが、精度は本来より
   低くなっています。ブラウザ版ツールの `nar_fullpage_parser.js` に
   実装済みの直近5走詳細抽出ロジックを、netkeiba形式向けに移植して
   `predict.py` に接続することを強く推奨します。
3. **「該当レース無し」判定**: `scraper_netkeiba.py` 内の判定条件は
   暫定的です。実際にレースが存在しない日付・レース番号でアクセスした
   際の画面を確認し、より確実な条件に調整してください。
4. **レース情報(距離・クラス)の抽出**: `predict.py` の
   `guess_race_meta()` は簡易的な正規表現です。実際のページ構造に
   合わせて精度を確認・改善してください。

## 次にやると良いこと

1. 上記の未接続部分(直近5走詳細)を実装し、ブラウザ版ツールと予想結果が
   一致するか照合する
2. 小規模(1日・1場)でテスト運用してから GitHub Actions の cron を有効化する
3. 本番運用前に robots.txt と利用規約を再確認する
