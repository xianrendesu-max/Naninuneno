import os
import httpx
import base64
from fastapi import FastAPI, Request, Response, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from bs4 import BeautifulSoup
from urllib.parse import urljoin

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# 規制回避のために削除・変更するヘッダー
UNWANTED_HEADERS = [
    "content-security-policy", "x-frame-options", "x-content-type-options",
    "x-xss-protection", "content-encoding"
]

# 広告ブロック対象キーワード
AD_KEYWORDS = ["googleads", "doubleclick", "adservice", "analytics", "adsbygoogle", "adnxs"]

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/proxy")
async def proxy(request: Request, b64url: str = Query(...)):
    try:
        # URLを難読化解除
        url = base64.b64decode(b64url).decode('utf-8')
    except Exception:
        return Response("URL Decode Error", status_code=400)

    try:
        async with httpx.AsyncClient(follow_redirects=True, verify=False, timeout=30.0) as client:
            # ターゲットへは「普通のアクセス」を装う
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
                "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
                "Referer": url
            }
            
            response = await client.get(url, headers=headers)
            content_type = response.headers.get("Content-Type", "")

            # HTMLコンテンツの高度な書き換え
            if "text/html" in content_type:
                soup = BeautifulSoup(response.text, "html.parser")
                
                # Baseタグを最優先で挿入
                base_tag = soup.new_tag('base', href=url)
                if soup.head:
                    soup.head.insert(0, base_tag)

                # 全てのリソースパスをプロキシURL（Base64）に置換
                for tag, attr in [('a', 'href'), ('img', 'src'), ('link', 'href'), ('script', 'src'), ('form', 'action'), ('source', 'src')]:
                    for el in soup.find_all(tag):
                        if el.has_attr(attr):
                            orig = el[attr]
                            if not orig.startswith(('javascript:', 'data:', '#')):
                                full_url = urljoin(url, orig)
                                encoded = base64.b64encode(full_url.encode()).decode()
                                el[attr] = f"/proxy?b64url={encoded}"

                # 広告要素の除去
                for ad in soup.find_all(['script', 'iframe', 'ins']):
                    src = ad.get('src', '') or ad.get('href', '')
                    if any(kw in src for kw in AD_KEYWORDS):
                        ad.decompose()

                content = str(soup)
            else:
                # 画像やJS、CSSはそのままバイナリで返す
                content = response.content

            # レスポンスの構築（セキュリティヘッダーを剥がす）
            proxy_res = Response(content=content, media_type=content_type)
            for k, v in response.headers.items():
                if k.lower() not in UNWANTED_HEADERS:
                    proxy_res.headers[k] = v
            
            # iframe内での動作を強制許可
            proxy_res.headers["Access-Control-Allow-Origin"] = "*"
            proxy_res.headers["X-Frame-Options"] = "ALLOWALL"
            
            return proxy_res

    except Exception as e:
        return HTMLResponse(content=f"<div style='color:white;background:#222;padding:20px;'>Connection Error: {e}</div>", status_code=500)
