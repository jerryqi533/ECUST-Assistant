import os
import json
import logging
import httpx
import uvicorn
import openai
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from sse_starlette.sse import EventSourceResponse
from contextlib import asynccontextmanager

# --- 配置与初始化 ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 建议在 Zeabur 的环境变量中设置这些 Key
KIMI_KEY = os.getenv("KIMI_KEY", "sk-TwR4oPmZFW7ljDZL7QK8FVp7hxEZHTMo0knLgj1RFLzurlxo").strip()
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "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").strip()

# 系统提示词：保留核心固定事实，同时引导 AI 介绍校区
SYSTEM_PROMPT = """你是华理信管小助手。
今天是 2026年1月21日。

【核心事实库】（优先使用）：
1. 寒假时间：2026年1月24日开始，3月1日结束。
2. 奉贤天气：今日最高 4℃，最低 -1℃。

【校区介绍引导】：
当用户询问奉贤校区时，请结合联网搜索到的最新信息（如校园美景、新开设施、交通变动等）进行介绍。
奉贤校区特点：海边校区（风大）、通海湖、图书馆（五角大楼）、青春活力。

回答风格：亲切、专业、像学长学姐一样。"""

# 初始化 OpenAI 客户端
client = openai.OpenAI(api_key=KIMI_KEY, base_url="https://api.moonshot.cn/v1")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 华理信管小助手服务启动中...")
    yield


app = FastAPI(title="华理信管小助手", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


async def search_web(query: str):
    """抓取华理相关实时信息"""
    if not TAVILY_API_KEY:
        return ""
    try:
        async with httpx.AsyncClient() as http_client:
            url = "https://api.tavily.com/search"
            # 这里的搜索词会自动包含“华东理工大学”以增加准确性
            payload = {
                "api_key": TAVILY_API_KEY,
                "query": f"华东理工大学 奉贤校区 {query} 最新情况",
                "search_depth": "news",
                "max_results": 3
            }
            response = await http_client.post(url, json=payload, timeout=10.0)
            results = response.json().get("results", [])
            return "\n".join([f"内容: {r['content']}" for r in results])
    except Exception as e:
        logger.error(f"⚠️ 搜索失败: {e}")
        return ""


async def kimi_stream(question: str):
    """流式生成器核心逻辑"""

    # 1. 仅拦截最基础的放假日期（确保绝对准确）
    if any(k in question for k in ["寒假", "放假时间", "什么时候开学"]):
        yield json.dumps({"answer": "同学你好！华理2026年寒假时间为：**1月24日至3月1日**。假期记得带好随身物品哦！🎒"},
                         ensure_ascii=False)
        yield json.dumps({"done": True})
        return

    # 2. 其他问题（包括奉贤校区介绍、天气询问等）全部走联网搜索逻辑
    # 这样可以获取到最新的校区新闻或实时的天气描述
    search_info = await search_web(question)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": f"实时搜索参考信息：\n{search_info}" if search_info else "未搜到校区最新动态"},
        {"role": "user", "content": question}
    ]

    try:
        stream = client.chat.completions.create(
            model="moonshot-v1-8k",
            messages=messages,
            stream=True
        )
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                content = chunk.choices[0].delta.content
                yield json.dumps({"answer": content}, ensure_ascii=False)

        yield json.dumps({"done": True})
    except Exception as e:
        logger.error(f"❌ Kimi 调用异常: {e}")
        yield json.dumps({"answer": "哎呀，网络开小差了，请重新问我一次吧。"}, ensure_ascii=False)
        yield json.dumps({"done": True})


# --- 路由配置 ---
@app.get("/")
async def root():
    return RedirectResponse(url="/chat-ui")


@app.get("/chat")
async def chat(q: str):
    return EventSourceResponse(kimi_stream(q.strip()))


@app.get("/chat-ui", response_class=HTMLResponse)
async def get_ui():
    return HTML_TEMPLATE


# --- 页面模板 ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>华理信管小助手</title>
    <style>
        body { font-family: -apple-system, system-ui, sans-serif; background: #f4f7f9; margin: 0; display: flex; justify-content: center; height: 100vh; }
        .chat-container { width: 100%; max-width: 500px; background: white; display: flex; flex-direction: column; box-shadow: 0 10px 25px rgba(0,0,0,0.05); }
        .header { background: #004ea2; color: white; padding: 20px; text-align: center; font-size: 1.1em; font-weight: bold; }
        #box { flex: 1; overflow-y: auto; padding: 20px; display: flex; flex-direction: column; gap: 15px; }
        .msg { max-width: 85%; padding: 12px 16px; border-radius: 15px; line-height: 1.5; font-size: 15px; word-wrap: break-word; }
        .user { background: #004ea2; color: white; align-self: flex-end; border-bottom-right-radius: 2px; }
        .ai { background: #f0f2f5; color: #333; align-self: flex-start; border-bottom-left-radius: 2px; }
        .input-area { padding: 20px; border-top: 1px solid #eee; display: flex; gap: 10px; background: white; }
        input { flex: 1; padding: 12px; border: 1px solid #ddd; border-radius: 8px; outline: none; }
        button { background: #004ea2; color: white; border: none; padding: 0 20px; border-radius: 8px; cursor: pointer; font-weight: bold; }
    </style>
</head>
<body>
    <div class="chat-container">
        <div class="header">华理信管小助手 (联网增强版)</div>
        <div id="box">
            <div class="msg ai">你好！想了解奉贤校区的最新情况，或者是寒假安排吗？尽管问我吧！🌊</div>
        </div>
        <div class="input-area">
            <input type="text" id="userInput" placeholder="例如：介绍一下奉贤校区..." onkeypress="if(event.keyCode==13) send()">
            <button onclick="send()">发送</button>
        </div>
    </div>
    <script>
        const box = document.getElementById('box');
        const input = document.getElementById('userInput');

        async function send() {
            const q = input.value.trim();
            if (!q) return;

            box.innerHTML += `<div class="msg user">${q}</div>`;
            input.value = '';
            box.scrollTop = box.scrollHeight;

            const aiDiv = document.createElement('div');
            aiDiv.className = 'msg ai';
            aiDiv.innerHTML = '正在查询实时信息并思考...';
            box.appendChild(aiDiv);

            const source = new EventSource('/chat?q=' + encodeURIComponent(q));
            let fullText = '';

            source.onmessage = (e) => {
                const data = JSON.parse(e.data);
                if (data.answer) {
                    if (fullText === '') aiDiv.innerHTML = ''; 
                    fullText += data.answer;
                    aiDiv.innerHTML = fullText.replace(/\\n/g, '<br>').replace(/\\*\\*(.*?)\\*\\*/g, '<strong>$1</strong>');
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
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)