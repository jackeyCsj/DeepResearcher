import uvicorn


if __name__ == "__main__":
    uvicorn.run(
        "client.api.app:app",
        host="0.0.0.0",
        port=8001,
        reload=True,
        reload_dirs=["client", "configs"],
        # 写成目录名而非通配符：uvicorn 会把 "data/**" 这类模式 glob 展开成
        # 上千个子目录再做 O(n^2) 去重，导致启动阶段卡死数分钟。
        reload_excludes=["data", "logs", "web/node_modules"],
    )
