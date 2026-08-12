# 南関東競馬AI 自動化パイプライン(雛形)

## データソースについて(重要)

**keiba.go.jp(地方競馬情報サイト)はrobots.txtで自動アクセスを禁止しています。**
実際にfetchツールで確認したところ `ROBOTS_DISALLOWED` としてブロックされました。
このサイトを対象にした自動スクレイピングは行わないでください。

**netkeiba(nar.netkeiba.com)は、少なくとも `race/newspaper.html` について
2026年8月13日時点でrobots.txtによるブロックが確認されませんでした。**
ただし以下の点にご注意ください:
- robots.txtは変更される可能性があるので、本番運用前に必ず
  `https://nar.netkeiba.com/robots.txt` を直接確認してください
- 利用規約(`https://www.netkeiba.com/info/kiyaku.html`)も確認してください
- ページ本体はJavaScriptで描画されるため、単純なHTTPリクエストでは
  出馬表テーブルの中身が取得できません。Playwrightなどのヘッドレスブラウザが必要です

## URL構造(確認済み)

```
https://nar.netkeiba.com/race/newspaper.html?race_id={race_id}
race_id = {年4桁}{場コード2桁}{月日4桁}{レース番号2桁}  (計12桁)

南関東の場コード: 浦和=42, 船橋=43, 大井=44, 川崎=45
例: 2025年12月29日 大井11R → race_id = 202544122911
```

## モデルの設計方針

**このモデルは馬体重を特徴量に使いません。** 検証の結果、馬体重の有無で精度はほぼ
変わらなかった(単勝AUC: 馬体重あり0.731 → なし0.737、複勝AUC: 0.743 → 0.736)ため、
思い切って除外しました。単勝オッズも元々使っていません。

これにより、**出馬表が発表された時点(通常レース前日)ならいつでもスクレイピング→予想が可能**
になります。

## 構成

```
scraper_skeleton/
├── scraper.py                  # (旧) keiba.go.jp向け - 使用非推奨、参考用に残置
├── scraper_netkeiba.py         # netkeiba向け Playwrightスクレイパー
├── predict.py                  # 予想パイプライン(雛形。詳細特徴量抽出は要実装)
└── .github/workflows/
    ├── scrape_and_predict.yml           # (旧) keiba.go.jp向け - 使用非推奨
    └── scrape_and_predict_netkeiba.yml  # netkeiba向け新ワークフロー
```

## 未実装・要確認の項目(正直な現状)

1. **newspaper.html vs shutuba_past.html の選択**: 添付いただいたサンプルは
   「競馬新聞」形式(newspaper.html)に近い構造でしたが、実際にPlaywrightで
   レンダリングした結果を見て、必要な情報が過不足なく取れるページを選定してください。
   他の候補: `shutuba_past.html`(馬柱5走)、`shutuba_past_9.html`(馬柱9走)
2. **「該当レース無し」判定の精度**: `scraper_netkeiba.py` の
   `scrape_race()` 内の判定条件(`empty paramter` 文字列の有無)は暫定的なものです。
   実際にレースが存在しない日付・レース番号でアクセスした際の画面を確認し、
   より確実な判定条件に調整してください。
3. **詳細特徴量抽出のPython移植**: 直近5走の人気・着差・上がり3F・通過順などの
   詳細抽出ロジックは、現在ブラウザ版ツール(`nar_fullpage_parser.js`)にのみ
   実装されています。自動化パイプラインで使うには、`detailed_parser.py`
   (Python版、動作確認済み)をこの `predict.py` に接続してください。
4. **モデルの読み込み**: `model_early_urawa_is_win.txt` / `_is_top3.txt` を
   `predict.py` から読み込んで実際にスコアリングする処理はTODOのままです。

## 次にやると良いこと

- Playwrightをインストールし、`scraper_netkeiba.py` を1レース分だけ手動実行して
  実際にどんなHTML/テキストが取れるか確認する
- 取れたテキストを `nar_fullpage_parser.js` の解析ロジック(Python移植版)に通し、
  ブラウザ版ツールでの手動貼り付け予想結果と一致するか照合する
- 小規模(1日・1場)でテスト運用してから GitHub Actions の cron を有効化する
- 本番運用前に robots.txt と利用規約を再確認する

