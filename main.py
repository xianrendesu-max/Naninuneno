import os
import httpx
import base64
import re
from fastapi import FastAPI, Request, Response, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# ISGC回避＆iframe動作のためのヘッダー削除リスト
STRIP_HEADERS = [
    "content-security-policy", "x-frame-options", "x-content-type-options",
    "x-xss-protection", "strict-transport-security", "content-encoding",
    "referrer-policy"
]

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/lib/js/common.bin")
async def stealth_proxy(request: Request, v: str = Query(...)):
    try:
        # 難読化URLを復号
        target_url = base64.b64decode(v).decode('utf-8')
    except Exception:
        return Response(content="Invalid URL Data", status_code=400)

    try:
        # SSL検証をスキップし、リダイレクトを追跡
        async with httpx.AsyncClient(follow_redirects=True, verify=False, timeout=30.0) as client:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                "Accept": "*/*",
                "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
                "Referer": target_url
            }
            resp = await client.get(target_url, headers=headers)
            ctype = resp.headers.get("Content-Type", "").lower()

            # HTMLの書き換え（デザイン崩れ防止）
            if "text/html" in ctype:
                soup = BeautifulSoup(resp.text, "html.parser")
                
                # Baseタグをヘッドの最上部に挿入（相対パス解決の要）
                base_tag = soup.new_tag('base', href=target_url)
                if soup.head:
                    soup.head.insert(0, base_tag)
                else:
                    new_head = soup.new_tag('head')
                    new_head.insert(0, base_tag)
                    soup.insert(0, new_head)

                # 全てのリソースパスをプロキシURLに強制置換
                tags_attrs = {
                    'a': 'href', 'img': 'src', 'link': 'href', 'script': 'src',
                    'form': 'action', 'source': 'src', 'video': 'src', 'audio': 'src', 'iframe': 'src'
                }

                for tag, attr in tags_attrs.items():
                    for el in soup.find_all(tag):
                        if el.has_attr(attr):
                            orig = el[attr]
                            if not orig.startswith(('javascript:', 'data:', '#')):
                                full = urljoin(target_url, orig)
                                enc = base64.b64encode(full.encode()).decode()
                                el[attr] = f"/lib/js/common.bin?v={enc}"

                # インラインCSS内の url() 書き換え (背景画像などが壊れないようにする)
                styles = soup.find_all("style")
                for s in styles:
                    if s.string:
                        # cssのurl(...)を検出し、プロキシURLへ置換
                        def css_url_replacer(match):
                            url = match.group(1).strip("'\"")
                            if not url.startswith(('data:', 'http')):
                                url = urljoin(target_url, url)
                            e = base64.b64encode(url.encode()).decode()
                            return f'url("/lib/js/common.bin?v={e}")'
                        s.string = re.sub(r'url\((.*?)\)', css_url_replacer, s.string)

                content = str(soup)
            else:
                # 画像、JS、CSS、フォントなどはバイナリでそのまま中継
                content = resp.content

            # レスポンスの構築
            final_res = Response(content=content, media_type=ctype)
            for k, v in resp.headers.items():
                if k.lower() not in STRIP_HEADERS:
                    final_res.headers[k] = v
            
            final_res.headers["X-Frame-Options"] = "ALLOWALL"
            final_res.headers["Access-Control-Allow-Origin"] = "*"
            return final_res

    except Exception as e:
        return HTMLResponse(content=f"<div style='color:red;'>Connection Error: {e}</div>", status_code=500)
