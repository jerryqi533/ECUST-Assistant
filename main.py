import os
import logging
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
import httpx
import uvicorn

# --- 配置日志 ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ECUST_Assistant")

app = FastAPI(title="华理信管小助手-联网增强版")

# --- 环境变量读取 ---
MOONSHOT_API_KEY = os.getenv("MOONSHOT_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

# --- 前端 HTML 模板 ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>华理信管小助手 - 联网增强版</title>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <style>
        :root { --primary-color: #004098; --bg-color: #f4f7f9; --chat-bg: #ffffff; --user-msg: #e3f2fd; --ai-msg: #f1f3f4; }
        body, html { height: 100%; margin: 0; font-family: 'PingFang SC', sans-serif; background-color: var(--bg-color); }
        .container { max-width: 800px; margin: 0 auto; height: 100vh; display: flex; flex-direction: column; background: white; }
        header { background: var(--primary-color); color: white; padding: 15px 20px; display: flex; justify-content: space-between; align-items: center; }
        #chat-window { flex: 1; overflow-y: auto; padding: 20px; display: flex; flex-direction: column; gap: 15px; border-bottom: 1px solid #eee; }
        .message { max-width: 85%; padding: 12px 16px; border-radius: 12px; line-height: 1.6; word-wrap: break-word; }
        .user-message { align-self: flex-end; background-color: var(--user-msg); color: #1a237e; border-bottom-right-radius: 2px; }
        .ai-message { align-self: flex-start; background-color: var(--ai-msg); color: #333; border-bottom-left-radius: 2px; white-space: pre-wrap; }
        .status-indicator { font-size: 0.8rem; color: #666; margin-bottom: 8px; display: flex; align-items: center; gap: 6px; }
        .input-area { padding: 20px; display: flex; gap: 10px; background: #fff; }
        input[type="text"] { flex: 1; padding: 12px 18px; border: 1px solid #ddd; border-radius: 25px; outline: none; font-size: 1rem; }
        input[type="text"]:focus { border-color: var(--primary-color); }
        button { background: var(--primary-color); color: white; border: none; width: 45px; height: 45px; border-radius: 50%; cursor: pointer; display: flex; align-items: center; justify-content: center; transition: 0.2s; }
        button:hover { opacity: 0.9; transform: scale(1.05); }
        .dots span { display: inline-block; width: 6px; height: 6px; background: #999; border-radius: 50%; animation: bounce 1.4s infinite ease-in-out; }
        .dots span:nth-child(2) { animation-delay: 0.2s; }
        .dots span:nth-child(3) { animation-delay: 0.4s; }
        @keyframes bounce { 0%, 80%, 100% { transform: scale(0); } 40% { transform: scale(1); } }
    </style>
</head>
<body>
<div class="container">
    <header>
        <div><i class="fas fa-university"></i> 华理信管小助手 <small style="font-size:0.7rem; opacity:0.8;">V2.0</small></div>
        <div style="font-size: 0.8rem;"><i class="fas fa-globe"></i> 联网模式</div>
    </header>
    <div id="chat-window">
        <div class="message ai-message">你好！我是联网增强版小助手。你可以问我关于华理的任何信息（如：最新的寒假安排、校园生活指南等）。</div>
    </div>
    <div class="input-area">
        <input type="text" id="userInput" placeholder="输入您的问题..." onkeypress="if(event.keyCode==13) sendMessage()">
        <button id="sendBtn" onclick="sendMessage()"><i class="fas fa-paper-plane"></i></button>
    </div>
</div>
<script>
    const chatWindow = document.getElementById('chat-window');
    const userInput = document.getElementById('userInput');
    async function sendMessage() {
        const text = userInput.value.trim();
        if (!text) return;
        appendMsg(text, 'user-message');
        userInput.value = '';
        const loadingId = appendLoading();
        try {
            const res = await fetch(`/chat?q=${encodeURIComponent(text)}`);
            const data = await res.json();
            removeEl(loadingId);
            appendMsg(data.answer, 'ai-message');
        } catch (e) {
            removeEl(loadingId);
            appendMsg("❌ 抱歉，连接服务器失败。", 'ai-message');
        }
    }
    function appendMsg(content, cls) {
        const d = document.createElement('div');
        d.className = `message ${cls}`;
        d.innerText = content;
        chatWindow.appendChild(d);
        chatWindow.scrollTop = chatWindow.scrollHeight;
    }
    function appendLoading() {
        const id = 'l-' + Date.now();
        const d = document.createElement('div');
        d.id = id; d.className = 'message ai-message';
        d.innerHTML = '<div class="status-indicator"><i class="fas fa-search fa-spin"></i> 正在联网并思考...</div><div class="dots"><span></span><span></span><span></span></div>';
        chatWindow.appendChild(d);
        chatWindow.scrollTop = chatWindow.scrollHeight;
        return id;
    }
    function removeEl(id) { document.getElementById(id)?.remove(); }
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def read_root():
    return HTML_TEMPLATE


@app.get("/chat")
async def chat(q: str = Query(...)):
    # 1. 检查环境变量
    if not MOONSHOT_API_KEY or not TAVILY_API_KEY:
        return {"answer": "🔧 系统配置错误：请检查环境变量中的 API Keys。"}

    async with httpx.AsyncClient(timeout=45.0) as client:
        # 2. 强制执行联网搜索
        search_context = ""
        try:
            search_res = await client.post(
                "https://api.tavily.com/search",
                json={"api_key": TAVILY_API_KEY, "query": q, "max_results": 3}
            )
            if search_res.status_code == 200:
                results = search_res.json().get("results", [])
                search_context = "\n".join([f"内容:{r['content']}" for r in results])
        except Exception as e:
            logger.error(f"Search error: {e}")

        # 3. 调用 Moonshot API
        try:
            response = await client.post(
                "https://api.moonshot.cn/v1/chat/completions",
                headers={"Authorization": f"Bearer {MOONSHOT_API_KEY}"},
                json={
                    "model": "moonshot-v1-8k",
                    "messages": [
                        {"role": "system", "content": f"你是华理小助手。请结合以下资料回答：{search_context}"},
                        {"role": "user", "content": q}
                    ],
                    "temperature": 0.3
                }
            )

            if response.status_code == 401:
                return {"answer": "❌ 认证失败 (401)：请检查并更新 MOONSHOT_API_KEY。"}

            if response.status_code != 200:
                return {"answer": f"⚠️ API 返回错误 (HTTP {response.status_code})"}

            data = response.json()
            return {"answer": data['choices'][0]['message']['content']}

        except Exception as e:
            return {"answer": f"⚠️ 发生预期外错误: {str(e)}"}


if __name__ == "__main__":
    # Zeabur 部署必须使用 0.0.0.0 和从环境获取的端口
    port = int(os.getenv("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)