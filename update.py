import json
from datetime import datetime

# 過去のニュースや新しいニュースをマージして「過去5日分」を維持・管理するスクリプト
def update_news():
    # 1. 実際に動かす際はここで各RSS（Runway, Luma, Pika, CGWORLD, プレスリリース等）を
    # feedparser等を使って取得し、キーワード（動画生成、アップスケーリング等）でフィルタリングします。
    
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    # 今回新たに「自動収集された」と仮定する最新のニュースデータ
    new_articles = [
        {
            "id": 101,
            "category": "global",
            "title": "Runway Announces Major Upgrade to Gen-3 with Advanced Frame Interpolation",
            "translatedTitle": "Runway、高度なフレーム補間機能を備えたGen-3の大規模アップデートを発表",
            "date": today_str,
            "source": "Runway Research",
            "url": "https://runwayml.com",
            "summary": "動画の滑らかさと物理一貫性が飛躍的に向上し、カクつきのない長尺フレーム生成が可能になりました。",
            "isEnglish": True
        },
        {
            "id": 102,
            "category": "japan",
            "title": "国内VFXスタジオ、AI超解像とフレーム生成を活用した4K映像制作ワークフローを導入",
            "translatedTitle": "",
            "date": today_str,
            "source": "CGWORLD.jp",
            "url": "https://cgworld.jp",
            "summary": "実写映像のアップスケーリングおよびAIによる中間フレーム補間を組み合わせ、制作時間を大幅に短縮。",
            "isEnglish": False
        }
    ]

    # 2. 既存の news.json を読み込む（なければ空リスト）
    try:
        with open("news.json", "r", encoding="utf-8") as f:
            existing_news = json.load(f)
    except FileNotFoundError:
        existing_news = []

    # 3. 新しいニュースを先頭に追加
    # 重複を防ぐため、同じタイトルのものがなければ追加する
    existing_titles = [item["title"] for item in existing_news]
    for article in new_articles:
        if article["title"] not in existing_titles:
            existing_news.insert(0, article)

    # 4. 日付が古すぎるもの（過去5日より前など）を削除してスッキリさせる
    # ここではシンプルに最新の20件程度に絞る処理にしておきます
    existing_news = existing_news[:20]

    # 5. news.json に書き戻す
    with open("news.json", "w", encoding="utf-8") as f:
        json.dump(existing_news, f, ensure_ascii=False, indent=4)
    
    print(f"Successfully updated news.json on {today_str}")

if __name__ == "__main__":
    update_news()
