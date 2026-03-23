from fastapi import FastAPI, HTTPException
import svara_inference
import os
import requests

app = FastAPI()

@app.get("/health")
def health_check():
    # Checks if GPU is reachable and ComfyUI is up
    try:
        response = requests.get("http://127.0.0.1:8188/history")
        return {"status": "ready", "comfy_status": response.status_code}
    except:
        return {"status": "warming_up", "message": "ComfyUI not yet reachable"}

@app.post("/generate-reel")
async def generate_reel(script: str, property_img: str):
    # Logic to trigger Svara and then ComfyUI
    print(f"Request received for: {script[:20]}...")
    # ... previous logic ...
    return {"job_id": "12345", "status": "queued"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
