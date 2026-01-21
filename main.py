import os
import logging
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
import httpx
import uvicorn

# --- 配置日志 ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ECUST_Assistant")

app = FastAPI()

# --- 环境变量 (请在 Zeabur 重新配置) ---
# 1. Moonshot API Key (从 platform.moonshot.cn 获取)
MOONSHOT_API_KEY = os.getenv("MOONSHOT_API_KEY")
# 2. Bocha API Key (从 open.bochaai.com 获取，国产搜索首选)
BOCHA_API_KEY = os.getenv("BOCHA_API_KEY")

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>华理信管小助手 - 国内增强版</title>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <style>
        :root { --primary-color: #004098; --bg-color: #f0f2f5; }
        body, html { height: 100%; margin: 0; font-family: 'PingFang SC', sans-serif; background-color: var(--bg-color); }
        .container { max-width: 700px; margin: 0 auto; height: 100vh; display: flex; flex-direction: column; background: white; }
        header { background: var(--primary-color); color: white; padding: 15px; text-align: center; font-weight: bold; }
        #chat-window { flex: 1; overflow-y: auto; padding: 20px; display: flex; flex-direction: column; gap: 15px; }
        .message { max-width: 85%; padding: 12px; border-radius: 10px; line-height: 1.6; }
        .user-message { align-self: flex-end; background-color: #004098; color: white; }
        .ai-message { align-self: flex-start; background-color: #f1f3f4; color: #333; white-space: pre-wrap; border: 1px solid #ddd; }
        .input-area { padding: 15px; border-top: 1px solid #eee; display: flex; gap: 10px; }
        input { flex: 1; padding: 10px 15px; border: 1px solid #ddd; border-radius: 20px; outline: none; }
        button { background: #004098; color: white; border: none; padding: 0 20px; border-radius: 20px; cursor: pointer; }
        .loading-hint { font-size: 0.8rem; color: #888; margin-bottom: 5px; }
    </style>
</head>
<body>
<div class="container">
    <header>华理信管小助手 (国产 AI 搜索增强版)</header>
    <div id="chat-window">
        <div class="message ai-message">你好！我已接入国产博查(Bocha)搜索引擎，可以为你查询最新的华理教务、放假及校园周边信息。</div>
    </div>
    <div class="input-area">
        <input type="text" id="userInput" placeholder="问我关于华理的一切..." onkeypress="if(event.keyCode==13) sendMessage()">
        <button onclick="sendMessage()">发送</button>
    </div>
</div>
<script>
    async function sendMessage() {
        const input = document.getElementById('userInput');
        const text = input.value.trim();
        if(!text) return;
        append('user-message', text);
        input.value = '';
        const lId = append('ai-message', '正在通过国内信源检索资料...', true);
        try {
            const res = await fetch(`/chat?q=${encodeURIComponent(text)}`);
            const data = await res.json();
            document.getElementById(lId).innerText = data.answer;
        } catch (e) {
            document.getElementById(lId).innerText = "❌ 连接失败，请检查 API 配置。";
        }
    }
    function append(cls, txt, isL=false) {
        const d = document.createElement('div');
        const id = 'm-' + Date.now();
        d.id = id; d.className = 'message ' + cls;
        d.innerText = txt;
        document.getElementById('chat-window').appendChild(d);
        document.getElementById('chat-window').scrollTop = 99999;
        return id;
    }
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def home():
    return HTML_TEMPLATE


@app.get("/chat")
async def chat(q: str = Query(...)):
    if not MOONSHOT_API_KEY or not BOCHA_API_KEY:
        return {"answer": "🔧 环境变量未配置。请确保 MOONSHOT_API_KEY 和 BOCHA_API_KEY 已填入 Zeabur。"}

    async with httpx.AsyncClient(timeout=60.0) as client:
        # --- 1. 使用 Bocha AI 进行中文联网搜索 ---
        search_context = ""
        try:
            # Bocha API 参考：https://open.bochaai.com/
            bocha_res = await client.post(
                "https://api.bochaai.com/v1/web-search",
                headers={"Authorization": f"Bearer {BOCHA_API_KEY}"},
                json={
                    "query": q,
                    "freshness": "noLimit",  # 搜索时效性
                    "summary": True
                }
            )
            if bocha_res.status_code == 200:
                data = bocha_res.json()
                # 提取搜索到的网页摘要
                pages = data.get("data", {}).get("webPages", {}).get("value", [])
                search_context = "\n".join([f"来源:{p['name']} 摘要:{p['snippet']}" for p in pages[:3]])
                logger.info("Bocha 搜索成功")
        except Exception as e:
            logger.error(f"Bocha 搜索失败: {e}")

        # --- 2. 使用 Moonshot (Kimi) 整合回答 ---
        try:
            response = await client.post(
                "https://api.moonshot.cn/v1/chat/completions",
                headers={"Authorization": f"Bearer {MOONSHOT_API_KEY}"},
                json={
                    "model": "moonshot-v1-8k",
                    "messages": [
                        {"role": "system",
                         "content": f"你是一个华理校园专家。基于以下搜索到的最新信息回答。如果没有相关资料，请结合常识回答。资料：{search_context}"},
                        {"role": "user", "content": q}
                    ],
                    "temperature": 0.3
                }
            )

            if response.status_code == 200:
                return {"answer": response.json()['choices'][0]['message']['content']}
            else:
                return {"answer": f"❌ API 错误 (代码: {response.status_code})。请确认 Moonshot API Key 是否有效。"}
        except Exception as e:
            return {"answer": f"⚠️ 系统繁忙: {str(e)}"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8080)))