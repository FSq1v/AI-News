"""AI ニュースを各種 RSS から収集し news.json を更新するスクリプト。

- 海外・国内の AI 専門メディア / 研究機関ブログ / Google News 検索を巡回
- AI 関連記事だけを抽出し、トピック分類・重複除去・期間管理を行う
- 英語記事の見出しを無料の翻訳 API (MyMemory) で日本語化する
- 環境変数 ANTHROPIC_API_KEY があれば、代わりに Claude で見出し・要約を日本語化し
  「本日の要点」も生成する
"""

import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

import feedparser

NEWS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "news.json")
JST = timezone(timedelta(hours=9))
RETENTION_DAYS = 14
MAX_ARTICLES = 800
MAX_PER_FEED = 40
SUMMARY_CHARS = 280
TRANSLATE_LIMIT = 160
# MyMemory の無料枠: 1日 5,000 文字（MYMEMORY_EMAIL を設定すると 50,000 文字）。
# 6時間ごとに実行するので、1回あたりその 1/4 弱を上限にする
MYMEMORY_CHARS_PER_RUN = {False: 2500, True: 12000}
USER_AGENT = "Mozilla/5.0 (compatible; AI-News-Bot/2.0; +https://github.com/FSq1v/AI-News)"
CLAUDE_MODEL = "claude-opus-5-5"


def google_news(query, lang):
    if lang == "ja":
        params = "hl=ja&gl=JP&ceid=JP:ja"
    else:
        params = "hl=en-US&gl=US&ceid=US:en"
    return f"https://news.google.com/rss/search?q={quote(query + ' when:2d')}&{params}"


# (表示名, URL, 地域, 重み, AI記事のみに絞るか)
# 重み: 3 = 一次情報（研究機関・企業公式）, 2 = 専門メディア, 1 = 総合 / 検索
FEEDS = [
    # --- 海外: 一次情報 ---
    ("OpenAI", "https://openai.com/news/rss.xml", "global", 3, False),
    ("Google DeepMind", "https://deepmind.google/blog/rss.xml", "global", 3, False),
    ("Google AI", "https://blog.google/technology/ai/rss/", "global", 3, False),
    ("Hugging Face", "https://huggingface.co/blog/feed.xml", "global", 3, False),
    ("Microsoft AI", "https://blogs.microsoft.com/ai/feed/", "global", 3, False),
    ("NVIDIA", "https://blogs.nvidia.com/feed/", "global", 3, True),
    ("AWS Machine Learning", "https://aws.amazon.com/blogs/machine-learning/feed/", "global", 2, False),
    ("BAIR", "https://bair.berkeley.edu/blog/feed.xml", "global", 3, False),
    # --- 海外: 専門メディア ---
    ("MIT Technology Review", "https://www.technologyreview.com/topic/artificial-intelligence/feed", "global", 2, False),
    ("TechCrunch", "https://techcrunch.com/category/artificial-intelligence/feed/", "global", 2, False),
    ("VentureBeat", "https://venturebeat.com/category/ai/feed/", "global", 2, False),
    ("The Verge", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", "global", 2, False),
    ("Ars Technica", "https://arstechnica.com/ai/feed/", "global", 2, False),
    ("WIRED", "https://www.wired.com/feed/tag/ai/latest/rss", "global", 2, False),
    ("The Decoder", "https://the-decoder.com/feed/", "global", 2, False),
    ("IEEE Spectrum", "https://spectrum.ieee.org/feeds/topic/artificial-intelligence.rss", "global", 2, False),
    ("ZDNET", "https://www.zdnet.com/topic/artificial-intelligence/rss.xml", "global", 2, False),
    # --- 海外: 検索 ---
    ("Google News", google_news('"generative AI" OR "AI model" OR "large language model"', "en"), "global", 1, True),
    ("Google News", google_news('"AI video" OR "AI video generation" OR "OpenAI Sora" OR "Runway AI" OR "Google Veo"', "en"), "global", 1, True),
    ("Google News", google_news('"AI regulation" OR "AI Act" OR "AI policy"', "en"), "global", 1, True),
    # --- 国内: 専門メディア ---
    ("ITmedia AI+", "https://rss.itmedia.co.jp/rss/2.0/aiplus.xml", "japan", 2, False),
    ("AINOW", "https://ainow.ai/feed/", "japan", 2, False),
    ("Ledge.ai", "https://ledge.ai/feed/", "japan", 2, False),
    ("Publickey", "https://www.publickey1.jp/atom.xml", "japan", 2, True),
    ("GIGAZINE", "https://gigazine.net/news/rss_2.0/", "japan", 1, True),
    ("Impress Watch", "https://www.watch.impress.co.jp/data/rss/1.0/ipw/feed.rdf", "japan", 1, True),
    ("ASCII.jp", "https://ascii.jp/rss.xml", "japan", 1, True),
    ("CGWORLD", "https://cgworld.jp/feed/", "japan", 2, True),
    # --- 国内: 検索 ---
    ("Google News", google_news("生成AI", "ja"), "japan", 1, True),
    ("Google News", google_news("AI 動画生成 OR 画像生成AI", "ja"), "japan", 1, True),
    ("Google News", google_news("AI 規制 OR AI 政府 OR AI 法案", "ja"), "japan", 1, True),
]

AI_PATTERN = re.compile(
    r"(?<![A-Za-z])AI(?![A-Za-z])|\bA\.I\.|artificial intelligence|machine learning|deep learning|neural net|"
    r"\bLLMs?\b|\bGPT|ChatGPT|Claude|Gemini|Llama|Copilot|OpenAI|Anthropic|DeepMind|"
    r"language model|chatbot|\bSora\b|\bVeo\b|Midjourney|Stable Diffusion|diffusion model|"
    r"生成AI|人工知能|機械学習|深層学習|大規模言語モデル|ＡＩ|動画生成|画像生成",
    re.IGNORECASE,
)

# 表示ラベル -> キーワード。複数該当可。
TOPICS = {
    "models": ("モデル", r"\bLLMs?\b|language model|foundation model|\bGPT-?\d|Claude|Gemini|Llama|Mistral|Qwen|DeepSeek|open[- ]weight|大規模言語モデル|基盤モデル|言語モデル"),
    "media": ("映像・画像", r"video|image generat|text-to-image|diffusion|Sora|Runway|Midjourney|Veo|Kling|Pika|Luma|upscal|音声合成|music generat|動画生成|画像生成|映像|超解像|アップスケール|フレーム補間|イラスト"),
    "agents": ("エージェント", r"\bagents?\b|agentic|computer use|automation|エージェント|自動化"),
    "research": ("研究", r"research|paper|arXiv|benchmark|study|scientists|breakthrough|研究|論文|ベンチマーク|大学"),
    "business": ("ビジネス", r"funding|raises|\$\d|valuation|acquir|acquisition|revenue|IPO|startup|partnership|invest|資金調達|買収|提携|出資|売上|投資|スタートアップ|業務提携"),
    "policy": ("政策・規制", r"regulat|\blaw\b|lawsuit|copyright|AI Act|government|policy|senate|congress|ban|safety institute|規制|法案|法律|政府|省|著作権|訴訟|ガイドライン|安全"),
    "hardware": ("半導体・インフラ", r"\bGPU|chip|semiconductor|NVIDIA|data ?center|TPU|compute|半導体|データセンター|GPU|計算資源"),
    "products": ("製品・サービス", r"launch|release|rolls? out|now available|introduc|unveil|update|app\b|発表|リリース|提供開始|公開|搭載|新機能|アップデート"),
}
TOPIC_RES = {key: re.compile(pattern, re.IGNORECASE) for key, (_, pattern) in TOPICS.items()}

TRACKING_PARAMS = re.compile(r"^(utm_|fbclid|gclid|mc_|ref$|ref_src$|source$|cmpid$)")


def log(message):
    print(message, file=sys.stderr)


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=25) as response:
        return response.read()


def clean_text(raw):
    text = re.sub(r"<[^>]+>", " ", raw or "")
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([.,!?。、])", r"\1", text)
    # フィード定型文を除去
    text = re.sub(r"(The post .*? appeared first on .*?\.?$|Continue reading.*$|続きを読む.*$)", "", text).strip()
    if len(text) > SUMMARY_CHARS:
        text = text[:SUMMARY_CHARS].rstrip() + "…"
    return text


def canonical_url(url):
    parts = urlsplit(url.strip())
    if "news.google.com" in parts.netloc:
        return url.strip()
    query = [(k, v) for k, v in parse_qsl(parts.query) if not TRACKING_PARAMS.match(k)]
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path.rstrip("/"), urlencode(query), ""))


def title_key(title):
    return re.sub(r"[\W_]+", "", title.lower())[:60]


def is_japanese(text):
    return bool(re.search(r"[぀-ヿ一-鿿]", text or ""))


def entry_datetime(entry):
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        value = entry.get(key)
        if value:
            return datetime(*value[:6], tzinfo=timezone.utc)
    return None


def entry_image(entry):
    for media in entry.get("media_content", []) + entry.get("media_thumbnail", []):
        if media.get("url", "").startswith("http"):
            return media["url"]
    for link in entry.get("links", []):
        if link.get("rel") == "enclosure" and link.get("type", "").startswith("image") and link.get("href", "").startswith("http"):
            return link["href"]
    return ""


def classify(text):
    topics = [key for key, regex in TOPIC_RES.items() if regex.search(text)]
    return topics or ["general"]


def parse_feed(feed):
    name, url, region, weight, ai_only = feed
    try:
        parsed = feedparser.parse(fetch(url))
    except Exception as exc:  # 1つのフィードの失敗で全体を止めない
        log(f"  ! {name}: {exc}")
        return []

    now = datetime.now(timezone.utc)
    articles = []
    for entry in parsed.entries[:MAX_PER_FEED]:
        link = entry.get("link", "")
        title = clean_text(entry.get("title", ""))
        if not title or not link.startswith("http"):
            continue

        source = name
        if "news.google.com" in url:
            # Google News は「見出し - 媒体名」形式
            source = (entry.get("source") or {}).get("title") or source
            title = re.sub(r"\s+[-–|]\s+[^-–|]+$", "", title)

        summary = clean_text(entry.get("summary") or entry.get("description") or "")
        if "news.google.com" in url or summary.startswith(title[:30]):
            summary = ""

        text = f"{title} {summary}"
        if ai_only and not AI_PATTERN.search(text):
            continue

        published = entry_datetime(entry) or now
        if published > now:
            published = now
        if published < now - timedelta(days=RETENTION_DAYS):
            continue

        canonical = canonical_url(link)
        articles.append({
            "id": hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:12],
            "region": region,
            "topics": classify(text),
            "title": title,
            "titleJa": title if is_japanese(title) else "",
            "summary": summary,
            "summaryJa": summary if is_japanese(summary) else "",
            "lang": "ja" if is_japanese(title) else "en",
            "source": source,
            "url": link,
            "image": entry_image(entry),
            "published": published.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "weight": weight,
        })
    log(f"  - {name}: {len(articles)}")
    return articles


def load_existing():
    try:
        with open(NEWS_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    # 旧形式（配列）は id / URL が不完全なため引き継がない
    if not isinstance(data, dict):
        return {}
    return data


def merge(existing, fresh):
    by_id = {a["id"]: a for a in existing}
    seen_titles = {title_key(a["title"]): a["id"] for a in existing}

    # 重みの高い（一次情報に近い）記事を優先して残す
    for article in sorted(fresh, key=lambda a: -a["weight"]):
        key = title_key(article["title"])
        if article["id"] in by_id:
            old = by_id[article["id"]]
            for field in ("titleJa", "summaryJa"):
                if old.get(field) and not article.get(field):
                    article[field] = old[field]
            article["published"] = old["published"]
            by_id[article["id"]] = article
        elif key in seen_titles:
            continue
        else:
            by_id[article["id"]] = article
            seen_titles[key] = article["id"]

    cutoff = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    merged = [a for a in by_id.values() if a["published"] >= cutoff]
    merged.sort(key=lambda a: a["published"], reverse=True)
    return merged[:MAX_ARTICLES]


def claude_json(client, prompt, schema):
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=16000,
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user", "content": prompt}],
    )
    if response.stop_reason != "end_turn":
        raise RuntimeError(f"stop_reason={response.stop_reason}")
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)


def translate_free(articles):
    """MyMemory 翻訳 API で英語の見出しを日本語にする（新しい記事から順に、無料枠の範囲で）。"""
    email = os.environ.get("MYMEMORY_EMAIL", "").strip()
    budget = MYMEMORY_CHARS_PER_RUN[bool(email)]
    done = 0
    for article in articles:
        if article["lang"] != "en" or article["titleJa"]:
            continue
        title = article["title"][:450]
        if len(title) > budget:
            break
        params = {"q": title, "langpair": "en|ja"}
        if email:
            params["de"] = email
        try:
            result = json.loads(fetch("https://api.mymemory.translated.net/get?" + urlencode(params)))
        except Exception as exc:
            log(f"  ! translation failed: {exc}")
            break
        text = html.unescape((result.get("responseData") or {}).get("translatedText") or "").strip()
        if str(result.get("responseStatus")) != "200" or result.get("quotaFinished") or text.upper().startswith("MYMEMORY WARNING"):
            log(f"  ! translation quota reached: {result.get('responseDetails') or text[:80]}")
            break
        if is_japanese(text):
            article["titleJa"] = text
            done += 1
        budget -= len(title)
        time.sleep(0.5)
    log(f"  translated (MyMemory): {done}")


def translate(client, articles):
    targets = [a for a in articles if a["lang"] == "en" and not a["titleJa"]][:TRANSLATE_LIMIT]
    schema = {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "titleJa": {"type": "string"},
                        "summaryJa": {"type": "string"},
                    },
                    "required": ["id", "titleJa", "summaryJa"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["items"],
        "additionalProperties": False,
    }
    for start in range(0, len(targets), 20):
        batch = targets[start:start + 20]
        payload = [{"id": a["id"], "title": a["title"], "summary": a["summary"]} for a in batch]
        prompt = (
            "以下は英語の AI 関連ニュースです。各記事について、日本の新聞の見出しのような簡潔で正確な日本語見出し(titleJa)と、"
            "要点を 1〜2 文・120 字以内でまとめた日本語要約(summaryJa)を作成してください。"
            "summary が空の場合は見出しから読み取れる範囲で簡潔に書き、推測で事実を補わないでください。"
            "固有名詞（企業名・製品名）は一般的な表記に従ってください。\n\n"
            + json.dumps(payload, ensure_ascii=False)
        )
        try:
            result = claude_json(client, prompt, schema)
        except Exception as exc:
            log(f"  ! translation batch failed: {exc}")
            continue
        by_id = {a["id"]: a for a in batch}
        for item in result["items"]:
            if item["id"] in by_id:
                by_id[item["id"]]["titleJa"] = item["titleJa"].strip()
                by_id[item["id"]]["summaryJa"] = item["summaryJa"].strip()
    log(f"  translated: {len(targets)}")


def make_brief(client, articles):
    since = (datetime.now(timezone.utc) - timedelta(hours=36)).strftime("%Y-%m-%dT%H:%M:%SZ")
    recent = [a for a in articles if a["published"] >= since]
    recent.sort(key=lambda a: (a["weight"], a["published"]), reverse=True)
    recent = recent[:60]
    if not recent:
        return None
    schema = {
        "type": "object",
        "properties": {
            "headline": {"type": "string"},
            "points": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"text": {"type": "string"}, "ids": {"type": "array", "items": {"type": "string"}}},
                    "required": ["text", "ids"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["headline", "points"],
        "additionalProperties": False,
    }
    payload = [
        {"id": a["id"], "title": a["titleJa"] or a["title"], "summary": a["summaryJa"] or a["summary"], "source": a["source"]}
        for a in recent
    ]
    prompt = (
        "以下は直近 36 時間の AI 関連ニュースです。読者向けに「本日の要点」を作成してください。"
        "headline は全体を表す 30 字以内の一文。points は重要度順に 4〜6 件、各 80 字以内の日本語で、"
        "根拠となる記事の id を ids に入れてください。記事にない事実は書かないでください。\n\n"
        + json.dumps(payload, ensure_ascii=False)
    )
    try:
        brief = claude_json(client, prompt, schema)
    except Exception as exc:
        log(f"  ! brief failed: {exc}")
        return None
    brief["generatedAt"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return brief


def update_news():
    existing = load_existing()
    log(f"Fetching {len(FEEDS)} feeds...")
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(parse_feed, FEEDS))
    fresh = [a for result in results for a in result]

    # AI 専門の媒体以外の記事は、AI に触れていなければ除外する（過去に保存された分も含む）
    ai_sources = {name for name, _, _, _, ai_only in FEEDS if not ai_only}
    kept = [a for a in existing.get("articles", [])
            if a["source"] in ai_sources or AI_PATTERN.search(f"{a['title']} {a['summary']}")]
    articles = merge(kept, fresh)
    brief = existing.get("brief")

    if os.environ.get("ANTHROPIC_API_KEY"):
        import anthropic

        client = anthropic.Anthropic()
        translate(client, articles)
        brief = make_brief(client, articles) or brief
    else:
        translate_free(articles)

    failed = sum(1 for result in results if not result)
    data = {
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "feedCount": len(FEEDS),
        "topics": {key: label for key, (label, _) in TOPICS.items()},
        "brief": brief,
        "articles": articles,
    }
    with open(NEWS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")

    print(f"news.json: {len(articles)} articles ({len(fresh)} fetched, {failed} feeds empty)")
    if not fresh and not existing.get("articles"):
        sys.exit("No articles could be fetched.")


if __name__ == "__main__":
    update_news()
