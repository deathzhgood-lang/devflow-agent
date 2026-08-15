import uvicorn


if __name__ == "__main__":
    uvicorn.run("devflow.api:app", host="0.0.0.0", port=8000, reload=False)

