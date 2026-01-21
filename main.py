import os
import json
import asyncio
import logging
import httpx
import uvicorn
import openai
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from sse_starlette.sse import EventSourceResponse
from contextlib import asynccontextmanager

# --- 强制设置环境变量（放在最前面，确保一定生效） ---
os.environ["KIMI_KEY"] = "sk-TwR4oPmZFW7ljDZL7QK8FVp7hxEZHTMo0knLgj1RFLzurlxo"  # 填入你的Kimi Key
os.environ["TAVILY_API_KEY"] = "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"

# --- 配置与初始化 ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

KIMI_KEY = os.getenv("KIMI_KEY", "").strip()
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "").strip()
SIMULATION_MODE = not bool(KIMI_KEY)

SYSTEM_PROMPT = """你是华东理工大学信管小助手。
请记住今天是 2026年1月21日，正值寒假前夕。

回答规则：
1. **口吻自然**：像学长学姐一样交流，可以用“同学你好”、“建议去看看”等词汇。
2. **智能分类**：根据搜索结果，将信息分为【学术讲座】、【校园新闻】、【生活提醒】。
3. **拒绝陈旧**：绝对不要提到 2025 年及以前的信息。
4. **贴心建议**：如果正值寒假，提醒同学注意校车时间表或食堂开关门时间。
5. **简洁有力**：不要解释搜索过程，直接给干货。"""

if not SIMULATION_MODE:
    client = openai.OpenAI(api_key=KIMI_KEY, base_url="https://api.moonshot.cn/v1")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 华理信管小助手服务启动中...")
    logger.info(f"🔑 KIMI 激活状态: {'Yes' if not SIMULATION_MODE else 'No'}")
    yield


app = FastAPI(title="华理信管小助手", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"],
                   allow_headers=["*"])


async def search_web(query: str):
    """强制联网搜索逻辑"""
    if not TAVILY_API_KEY: return ""
    try:
        async with httpx.AsyncClient() as http_client:
            url = "https://api.tavily.com/search"
            payload = {"api_key": TAVILY_API_KEY, "query": query, "search_depth": "news", "max_results": 4}
            response = await http_client.post(url, json=payload, timeout=15.0)
            results = response.json().get("results", [])
            return "\n".join([f"内容: {r['content']}" for r in results])
    except Exception as e:
        logger.error(f"搜索失败: {e}")
        return ""


async def kimi_stream(question: str):
    """强制联网搜索的流式生成器"""
    try:
        if SIMULATION_MODE:
            # ... 模拟模式保持不变 ...
            return

        # --- 核心修改在这里 ---
        logger.info(f"🔍 正在执行全量搜索: {question}")

        # 将之前的强制关键词改为更灵活的组合
        refined_query = f"华东理工大学 2026年1月 {question} 最新公告 寒假安排"

        # 2. 调用搜索函数时，使用这个 refined_query 而不是原始的 question
        search_info = await search_web(refined_query)
        # ----------------------

        # 3. 构造消息给 Kimi
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        if search_info:
            messages.append({"role": "system", "content": f"实时信息：{search_info}"})
        messages.append({"role": "user", "content": question})

        # 4. 调用 Kimi API
        stream = client.chat.completions.create(model="moonshot-v1-8k", messages=messages, stream=True)
        # ... 后面的循环代码保持不变 ...
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield json.dumps({"answer": chunk.choices[0].delta.content}, ensure_ascii=False)
        yield json.dumps({"done": True}, ensure_ascii=False)
    except Exception as e:
        yield json.dumps({"answer": f"出错了: {str(e)}"}, ensure_ascii=False)
        yield json.dumps({"done": True}, ensure_ascii=False)


@app.get("/")
async def root(): return RedirectResponse(url="/chat-ui")


@app.get("/chat")
async def chat(q: str): return EventSourceResponse(kimi_stream(q.strip()))


@app.get("/chat-ui", response_class=HTMLResponse)
async def get_ui(): return HTML_TEMPLATE


# --- 注意此处字符串的闭合 ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>华理信管小助手</title>
    <style>
        body { font-family: sans-serif; background: #f0f2f5; display: flex; justify-content: center; padding: 20px; }
        .chat-container { width: 100%; max-width: 600px; background: white; border-radius: 12px; height: 80vh; display: flex; flex-direction: column; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.1); }
        .header { background: #004ea2; color: white; padding: 15px; text-align: center; font-weight: bold; }
        #box { flex: 1; overflow-y: auto; padding: 20px; }
        .input-area { padding: 15px; border-top: 1px solid #eee; display: flex; gap: 10px; }
        input { flex: 1; padding: 10px; border: 1px solid #ddd; border-radius: 4px; }
        button { background: #004ea2; color: white; border: none; padding: 10px 20px; border-radius: 4px; cursor: pointer; }
        .msg { margin-bottom: 10px; padding: 10px; border-radius: 8px; line-height: 1.6; }
        .user { background: #e3f2fd; align-self: flex-end; margin-left: 20%; }
        .ai { background: #f5f5f5; align-self: flex-start; margin-right: 20%; }
    </style>
</head>
<body>
    <div class="chat-container">
        <div class="header">华理信管小助手 (联网版)</div>
        <div id="box"></div>
        <div class="input-area">
            <input type="text" id="userInput" placeholder="输入问题...">
            <button onclick="send()">发送</button>
        </div>
    </div>
    <script>
        async function send() {
            const input = document.getElementById('userInput');
            const box = document.getElementById('box');
            const q = input.value.trim();
            if (!q) return;

            box.innerHTML += `<div class="msg user">${q}</div>`;
            const aiDiv = document.createElement('div');
            aiDiv.className = 'msg ai';
            aiDiv.innerHTML = '正在搜索并思考...';
            box.appendChild(aiDiv);
            input.value = '';

            const source = new EventSource('/chat?q=' + encodeURIComponent(q));
            let res = '';
            source.onmessage = (e) => {
                const data = JSON.parse(e.data);
                if (data.answer) {
                    res += data.answer;
                    aiDiv.innerHTML = res.replace(/\\n/g, '<br>');
                }
                if (data.done) source.close();
                box.scrollTop = box.scrollHeight;
            };
        }
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    # 获取 Zeabur 自动分配的端口，如果没有则默认 8080
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)