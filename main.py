import os
import httpx
import base64
import re
from fastapi import FastAPI, Request, Response, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from bs4 import BeautifulSoup
from urllib.parse import urljoin

app = FastAPI()

# templatesフォルダを使用するための設定
templates = Jinja2Templates(directory="templates")

# ISGCやブラウザの制限を解除するために削除するヘッダー
SHIELD_HEADERS = [
    "content-security-policy", 
    "x-frame-options", 
    "x-content-type-options",
    "x-xss-protection", 
    "strict-transport-security", 
    "content-encoding",
    "referrer-policy",
    "cross-origin-opener-policy"
]

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# エンドポイント：ISGCに怪しまれないよう「共通スクリプト」を装う
@app.get("/lib/js/common.bin")
async def stealth_proxy(request: Request, v: str = Query(...)):
    try:
        # Base64で難読化されたターゲットURLを復号
        target_url = base64.b64decode(v).decode('utf-8')
    except Exception:
        return Response(content="Invalid URL Parameter", status_code=400)

    try:
        # SSL検証(verify=False)を無効化し、リダイレクトを追跡
        async with httpx.AsyncClient(follow_redirects=True, verify=False, timeout=30.0) as client:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                "Accept": "*/*",
                "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
                "Referer": target_url
            }
            resp = await client.get(target_url, headers=headers)
            content_type = resp.headers.get("Content-Type", "").lower()

            # HTMLコンテンツの場合、リンクやスタイルをすべてプロキシ経由に書き換え
            if "text/html" in content_type:
                soup = BeautifulSoup(resp.text, "html.parser")
                
                # 絶対パス解決のためのBaseタグを最優先で挿入
                base_tag = soup.new_tag('base', href=target_url)
                if soup.head:
                    soup.head.insert(0, base_tag)
                else:
                    head = soup.new_tag('head')
                    head.insert(0, base_tag)
                    soup.insert(0, head)

                # 書き換え対象のタグと属性リスト
                rewrite_map = {
                    'a': 'href', 'img': 'src', 'link': 'href', 'script': 'src',
                    'form': 'action', 'source': 'src', 'video': 'src', 'audio': 'src', 'iframe': 'src'
                }

                for tag, attr in rewrite_map.items():
                    for el in soup.find_all(tag):
                        if el.has_attr(attr):
                            orig_val = el[attr]
                            # 無効なパスやJS実行を除外
                            if not orig_val.startswith(('javascript:', 'data:', '#', 'mailto:', 'tel:')):
                                # 相対パスを絶対URLに変換
                                full_path = urljoin(target_url, orig_val)
                                # URLを難読化してプロキシエンドポイントへ
                                encoded_path = base64.b64encode(full_path.encode()).decode()
                                el[attr] = f"/lib/js/common.bin?v={encoded_path}"

                # インラインCSS内の url() 関数を書き換え（背景画像など）
                for style_tag in soup.find_all("style"):
                    if style_tag.string:
                        def css_url_fixer(match):
                            url_match = match.group(1).strip("'\"")
                            if not url_match.startswith(('data:', 'http')):
                                url_match = urljoin(target_url, url_match)
                            e = base64.b64encode(url_match.encode()).decode()
                            return f'url("/lib/js/common.bin?v={e}")'
                        style_tag.string = re.sub(r'url\((.*?)\)', css_url_fixer, style_tag.string)

                body_data = str(soup)
            else:
                # 画像やJSバイナリなどはそのまま転送
                body_data = resp.content

            # レスポンス作成
            proxy_resp = Response(content=body_data, media_type=content_type)
            
            # 検閲・制限ヘッダーをフィルタリングしてコピー
            for key, value in resp.headers.items():
                if key.lower() not in SHIELD_HEADERS:
                    proxy_resp.headers[key] = value
            
            # iframe内での動作を強制許可
            proxy_resp.headers["X-Frame-Options"] = "ALLOWALL"
            proxy_resp.headers["Access-Control-Allow-Origin"] = "*"
            
            return proxy_resp

    except Exception as e:
        return HTMLResponse(content=f"<div style='background:#000;color:red;padding:20px;'>Connection Error: {str(e)}</div>", status_code=500)
