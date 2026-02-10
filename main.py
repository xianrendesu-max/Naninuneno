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

# ISGCに検閲されるヘッダーを徹底的に削除
STRIP_HEADERS = [
    "content-security-policy", "x-frame-options", "x-content-type-options",
    "x-xss-protection", "strict-transport-security", "content-encoding"
]

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/api/v1/assets")
async def proxy_engine(request: Request, d: str = Query(...)):
    try:
        # Base64デコード
        target_url = base64.b64decode(d).decode('utf-8')
    except Exception:
        return Response(status_code=400)

    try:
        # タイムアウトを30秒に延長し、検証をスキップ
        async with httpx.AsyncClient(follow_redirects=True, verify=False, timeout=30.0) as client:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
                "Accept": "*/*",
                "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
                "Connection": "keep-alive"
            }
            resp = await client.get(target_url, headers=headers)
            ctype = resp.headers.get("Content-Type", "")

            if "text/html" in ctype:
                soup = BeautifulSoup(resp.text, "html.parser")
                
                # Baseタグを挿入して相対パスの解決をブラウザに任せない（サーバーで制御）
                base_tag = soup.new_tag('base', href=target_url)
                if soup.head: soup.head.insert(0, base_tag)

                # すべてのリソースを難読化プロキシ経由に書き換え
                for tag, attr in [('a', 'href'), ('img', 'src'), ('link', 'href'), ('script', 'src'), ('form', 'action')]:
                    for el in soup.find_all(tag):
                        if el.has_attr(attr):
                            val = el[attr]
                            if not val.startswith(('javascript:', 'data:', '#')):
                                full = urljoin(target_url, val)
                                enc = base64.b64encode(full.encode()).decode()
                                el[attr] = f"/api/v1/assets?d={enc}"

                # 広告削除
                for ad in soup.select('script[src*="ads"], iframe[src*="ads"], ins.adsbygoogle'):
                    ad.decompose()

                content = str(soup)
            else:
                # 画像などはそのまま返す
                content = resp.content

            # ISGCの制限を上書き
            final_res = Response(content=content, media_type=ctype)
            for k, v in resp.headers.items():
                if k.lower() not in STRIP_HEADERS:
                    final_res.headers[k] = v
            
            final_res.headers["X-Frame-Options"] = "ALLOWALL"
            final_res.headers["Access-Control-Allow-Origin"] = "*"
            return final_res

    except Exception as e:
        return HTMLResponse(content=f"Connect Error: {str(e)}", status_code=500)
