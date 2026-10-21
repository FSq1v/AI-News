# AI Chronicle

海外・国内の人工知能（AI）関連ニュースを自動で収集し、新聞のような紙面で読めるニュースダイジェストです。

## 仕組み

- `update.py` が約30のRSSフィード（OpenAI・Google DeepMind などの公式ブログ、MIT Technology Review・TechCrunch・ITmedia AI+ などの専門メディア、Google ニュース検索）から記事を取得します
- AI に関係する記事だけを抽出し、分野（モデル／映像・画像／エージェント／研究／ビジネス／政策・規制／半導体・インフラ／製品・サービス）に自動分類します
- 同じ URL・同じ見出しの記事はまとめ、過去14日分（最大800件）を `news.json` に保存します
- GitHub Actions（`.github/workflows/update-news.yml`）が6時間ごとに実行し、`news.json` を自動コミットします
- `index.html` が `news.json` を読み込んで表示します（GitHub Pages で公開する想定）

## 日本語訳と「本日の要点」（任意）

リポジトリの **Settings → Secrets and variables → Actions** に `ANTHROPIC_API_KEY` を登録すると、更新のたびに次の処理も行います。

- 英語記事の見出しと要約を日本語に翻訳します
- 直近36時間の記事から「本日の要点」を作成します

キーを登録しない場合、英語記事は原文のまま表示され、「本日の要点」の欄には注目度の高い見出しが並びます。

## 画面の機能

- 総合／海外／国内のセクションと分野別の絞り込み
- キーワード検索（該当箇所を強調表示）、期間・出典・未読での絞り込み、注目度順の並び替え
- トップ記事の自動選定。複数の媒体が報じた話題を優先し、同じ話題は1本にまとめます
- 注目キーワードと分野別の記事数
- 保存（掲載期間を過ぎても残ります。Markdown で書き出せます）、閲覧履歴、既読管理、前回訪問以降の新着表示
- 原文と日本語訳の切り替え、ライト／ダーク表示、文字サイズの切り替え
- キーボード操作（`J`/`K` で移動、`O` で開く、`S` で保存、`/` で検索、`?` で一覧を表示）
- 絞り込み条件が URL に残るため、そのまま共有できます

## 手動で更新する

```bash
pip install -r requirements.txt
python update.py
python -m http.server  # http://localhost:8000 で確認
```

GitHub 上では **Actions → Update AI News → Run workflow** から手動で実行できます。
