from fastapi import FastAPI
import os

# 初始化 FastAPI 应用
app = FastAPI()

# 读取环境变量中的 KIMI 密钥
KIMI_KEY = os.getenv("KIMI_KEY")
if not KIMI_KEY:
    raise ValueError("未配置 KIMI_KEY 环境变量，请先设置！")

# 示例接口
@app.get("/")
async def root():
    return {"message": "FastAPI 应用已启动", "kimi_key": KIMI_KEY[:6] + "****"}  # 隐藏密钥大部分内容