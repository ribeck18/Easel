import uvicorn


if __name__ == "__main__":
    # Database creation and scheduler startup are owned by app.py's lifespan, which runs
    # when uvicorn imports the app below -- so this dev entry point, the native launcher,
    # and the test client all start up identically.
    uvicorn.run("app:app", host="0.0.0.0", port=8000)
