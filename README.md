# AI Chronicle

海外・国内の人工知能（AI）関連ニュースを自動で収集し、新聞のような紙面で読めるニュースダイジェストです。

## 仕組み

- `update.py` が約30のRSSフィード（OpenAI・Google DeepMind などの公式ブログ、MIT Technology Review・TechCrunch・ITmedia AI+ などの専門メディア、Google ニュース検索）から記事を取得します
- AI に関係する記事だけを抽出し、分野（モデル／映像・画像／エージェント／研究／ビジネス／政策・規制／半導体・インフラ／製品・サービス）に自動分類します
- 同じ URL・同じ見出しの記事はまとめ、過去14日分（最大800件）を `news.json` に保存します
- GitHub Actions（`.github/workflows/update-news.yml`）が6時間ごとに実行し、`news.json` を自動コミットします
- `index.html` が `news.json` を読み込んで表示します（GitHub Pages で公開する想定）

## 英語記事の日本語訳

英語記事の見出しは、無料の翻訳API [MyMemory](https://mymemory.translated.net/) で自動的に日本語にします。APIキーは不要です。

- 無料枠は1日5,000文字（見出し60件前後）です。新しい記事から順に訳し、枠を超えた分は次回以降に回します
- リポジトリの **Settings → Secrets and variables → Actions** に `MYMEMORY_EMAIL`（任意のメールアドレス）を登録すると、無料枠が1日50,000文字に増えます
- 各記事の「和訳で読む」から、記事本文を Google 翻訳で日本語にして読めます

`ANTHROPIC_API_KEY` を登録した場合は、MyMemory の代わりに Claude で見出しと要約を翻訳し、「本日の要点」も作成します（API利用料が別途かかります）。

## 画面の機能

- 総合／海外／国内のセクションと分野別の絞り込み
- キーワード検索（該当箇所を強調表示）、期間・出典・未読での絞り込み、注目度順の並び替え
- トップ記事の自動選定。複数の媒体が報じた話題を優先し、同じ話題は1本にまとめます
- 注目キーワードと分野別の記事数
- 保存（掲載期間を過ぎても残ります。Markdown で書き出せます）、閲覧履歴、既読管理、前回訪問以降の新着表示
- 原文と日本語訳の切り替え（英語の要約は原文表示のときだけ表示）、ライト／ダーク表示、文字サイズの切り替え
- キーボード操作（`J`/`K` で移動、`O` で開く、`S` で保存、`/` で検索、`?` で一覧を表示）
- 絞り込み条件が URL に残るため、そのまま共有できます

## 手動で更新する

```bash
pip install -r requirements.txt
python update.py
python -m http.server  # http://localhost:8000 で確認
```

GitHub 上では **Actions → Update AI News → Run workflow** から手動で実行できます。
