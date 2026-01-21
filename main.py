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

# --- 配置与日志 ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 从环境变量获取 Key
KIMI_KEY = os.getenv("KIMI_KEY", "sk-TwR4oPmZFW7ljDZL7QK8FVp7hxEZHTMo0knLgj1RFLzurlxo").strip()
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "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").strip()

SYSTEM_PROMPT = """你是华理信管小助手。今天是 2026年1月20日。
【背景知识】：
1. 寒假安排：2026年1月24日放假，3月1日开学。
2. 奉贤校区：位于海边，标志建筑是“五角大楼”图书馆，通海湖很美。
【指令】：
- 奉贤校区介绍：结合联网信息，介绍其地理位置、建筑特色、校园氛围（青春、风大、安静）。
- 语气：热情、学长口吻、多用 Emoji。"""

client = openai.OpenAI(api_key=KIMI_KEY, base_url="https://api.moonshot.cn/v1")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 华理小助手已启动")
    yield


app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


async def search_web(query: str):
    """优化后的搜索逻辑，增加了容错和超时处理"""
    if not TAVILY_API_KEY: return "无联网权限"
    try:
        async with httpx.AsyncClient() as http_client:
            # 针对奉贤校区进行搜索词优化
            search_query = f"华东理工大学 奉贤校区 {query} 最新情况 校园导览"
            response = await http_client.post(
                "https://api.tavily.com/search",
                json={"api_key": TAVILY_API_KEY, "query": search_query, "max_results": 3},
                timeout=8.0  # 稍微缩短超时，避免长时间挂起
            )
            data = response.json()
            return "\n".join([r['content'] for r in data.get("results", [])])
    except Exception as e:
        logger.warning(f"搜索接口波动: {e}")
        return "暂未获取到实时校区新闻，将基于校友经验回答。"


async def kimi_stream(question: str):
    """流式生成器：增加分类判断提高响应速度"""

    # 快速拦截：如果是简单的放假询问，不走搜索直接回答
    if any(k in question for k in ["寒假", "放假", "开学"]):
        yield json.dumps({"answer": "同学你好！华理2026年寒假时间：**1月24日 - 3月1日**。祝你假期愉快！✈️"},
                         ensure_ascii=False)
        yield json.dumps({"done": True})
        return

    # 联网获取最新信息
    context = await search_web(question)

    try:
        stream = client.chat.completions.create(
            model="moonshot-v1-8k",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "system", "content": f"实时参考信息：{context}"},
                {"role": "user", "content": question}
            ],
            stream=True,
            timeout=15.0
        )
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield json.dumps({"answer": chunk.choices[0].delta.content}, ensure_ascii=False)
        yield json.dumps({"done": True})
    except Exception as e:
        logger.error(f"API 报错: {e}")
        yield json.dumps(
            {"answer": "哎呀，网络波动中... 刚才说到奉贤校区，它可是著名的'海边大学'，风真的很大！建议你再问我一次~"},
            ensure_ascii=False)
        yield json.dumps({"done": True})


@app.get("/")
async def root(): return RedirectResponse(url="/chat-ui")


@app.get("/chat")
async def chat(q: str): return EventSourceResponse(kimi_stream(q))


@app.get("/chat-ui", response_class=HTMLResponse)
async def get_ui(): return HTML_TEMPLATE


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>华理信管小助手</title>
    <style>
        body { font-family: sans-serif; background: #f0f2f5; margin: 0; display: flex; justify-content: center; }
        .chat-container { width: 100%; max-width: 500px; background: white; height: 100vh; display: flex; flex-direction: column; }
        .header { background: #004ea2; color: white; padding: 15px; text-align: center; font-weight: bold; }
        #box { flex: 1; overflow-y: auto; padding: 20px; }
        .msg { margin-bottom: 15px; padding: 10px 15px; border-radius: 10px; line-height: 1.5; font-size: 15px; }
        .ai { background: #f0f2f5; align-self: flex-start; }
        .user { background: #004ea2; color: white; align-self: flex-end; margin-left: 15%; }
        .input-area { padding: 15px; border-top: 1px solid #ddd; display: flex; }
        input { flex: 1; padding: 10px; border: 1px solid #ccc; border-radius: 5px; outline: none; }
        button { background: #004ea2; color: white; border: none; padding: 0 15px; margin-left: 5px; border-radius: 5px; }
    </style>
</head>
<body>
    <div class="chat-container">
        <div class="header">华理信管小助手 (联网增强版)</div>
        <div id="box"></div>
        <div class="input-area">
            <input type="text" id="userInput" placeholder="问问奉贤校区介绍..." onkeypress="if(event.keyCode==13) send()">
            <button onclick="send()">发送</button>
        </div>
    </div>
    <script>
        const box = document.getElementById('box');
        async function send() {
            const input = document.getElementById('userInput');
            const q = input.value.trim();
            if(!q) return;
            box.innerHTML += `<div style="display:flex;flex-direction:column"><div class="msg user">${q}</div></div>`;
            input.value = '';
            const aiDiv = document.createElement('div');
            aiDiv.className = 'msg ai';
            aiDiv.innerHTML = '正在为您搜集奉贤校区资料...';
            box.appendChild(aiDiv);
            box.scrollTop = box.scrollHeight;

            const source = new EventSource('/chat?q=' + encodeURIComponent(q));
            let fullText = '';
            source.onmessage = (e) => {
                const data = JSON.parse(e.data);
                if(data.answer) {
                    if(fullText === '') aiDiv.innerHTML = '';
                    fullText += data.answer;
                    aiDiv.innerHTML = fullText.replace(/\\n/g, '<br>').replace(/\\*\\*(.*?)\\*\\*/g, '<b>$1</b>');
                }
                if(data.done) source.close();
                box.scrollTop = box.scrollHeight;
            };
            source.onerror = () => { source.close(); };
        }
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)