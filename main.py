import os
import httpx
from fastapi import FastAPI, Request, Response, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# 規制解除・互換性のためのヘッダーリスト
REMOVE_HEADERS = [
    "content-security-policy", "x-frame-options", "x-content-type-options",
    "x-xss-protection", "content-encoding", "set-cookie"
]

AD_PATTERNS = ["googleads", "doubleclick", "adservice", "analytics", "adsbygoogle"]

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/proxy")
async def proxy(request: Request, url: str = Query(...)):
    if not url.startswith("http"):
        url = "https://" + url

    try:
        async with httpx.AsyncClient(follow_redirects=True, verify=False, timeout=30.0) as client:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
                "Accept": "*/*",
                "Accept-Language": "ja,en-US;q=0.9,en;q=0.8"
            }
            
            response = await client.get(url, headers=headers)
            content_type = response.headers.get("Content-Type", "")

            # --- HTML書き換えロジック ---
            if "text/html" in content_type:
                soup = BeautifulSoup(response.text, "html.parser")
                
                # Baseタグ挿入（相対パスの崩れを防止）
                base_tag = soup.new_tag('base', href=url)
                if soup.head: soup.head.insert(0, base_tag)

                # リンク・リソースのプロキシ化
                for tag, attr in [('a', 'href'), ('img', 'src'), ('link', 'href'), ('script', 'src'), ('form', 'action'), ('source', 'src')]:
                    for el in soup.find_all(tag):
                        if el.has_attr(attr):
                            val = el[attr]
                            if not val.startswith(('javascript:', 'data:', '#')):
                                el[attr] = f"/proxy?url={urljoin(url, val)}"

                # 広告ブロック（特定のキーワードを含むタグを除去）
                for ad in soup.find_all(['script', 'iframe', 'ins']):
                    src = ad.get('src', '') or ad.get('href', '')
                    if any(p in src for p in AD_PATTERNS):
                        ad.decompose()

                content = str(soup)
            else:
                # 画像・CSS・JSなどはバイナリでそのまま中継
                content = response.content

            # --- レスポンス作成と規制回避 ---
            proxy_res = Response(content=content, media_type=content_type)
            for k, v in response.headers.items():
                if k.lower() not in REMOVE_HEADERS:
                    proxy_res.headers[k] = v
            
            # CORSとiframe許可を強制上書き
            proxy_res.headers["Access-Control-Allow-Origin"] = "*"
            proxy_res.headers["X-Frame-Options"] = "ALLOWALL"
            
            return proxy_res

    except Exception as e:
        return HTMLResponse(content=f"<div style='background:#1a1a1a;color:#ff4b4b;padding:20px;font-family:sans-serif;'><h2>Connection Failed</h2><p>{e}</p></div>")
