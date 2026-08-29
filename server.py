import uvicorn


if __name__ == "__main__":
    uvicorn.run(
        "client.api.app:app",
        host="0.0.0.0",
        port=8001,
        reload=True,
        reload_dirs=["client", "configs"],
        reload_excludes=[
            "data/*",
            "data/**",
            "logs/*",
            "logs/**",
            "web/node_modules/*",
            "web/node_modules/**",
        ],
    )
