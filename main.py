from fastapi import FastAPI, Request, Form, Query, Response
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from bs4 import BeautifulSoup
import httpx
import os
from urllib.parse import urljoin

app = FastAPI()
templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/proxy", response_class=HTMLResponse)
async def proxy(request: Request, url: str = Query(...)):
    if not url.startswith("http"):
        url = "https://" + url

    try:
        async with httpx.AsyncClient(follow_redirects=True, verify=False) as client:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
            response = await client.get(url, headers=headers)
            
            content_type = response.headers.get("Content-Type", "")
            
            # HTMLの場合、リンクを書き換える
            if "text/html" in content_type:
                soup = BeautifulSoup(response.text, "html.parser")
                for tag in soup.find_all(True):
                    for attr in ['href', 'src', 'action']:
                        if tag.has_attr(attr):
                            full_url = urljoin(url, tag[attr])
                            # プロキシ経由のパスに変換
                            tag[attr] = f"/proxy?url={full_url}"
                return HTMLResponse(content=str(soup))
            
            # 画像やCSSなどはそのまま中継
            return Response(content=response.content, media_type=content_type)
            
    except Exception as e:
        return HTMLResponse(content=f"Error: {str(e)}", status_code=500)

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
