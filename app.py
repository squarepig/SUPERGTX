from fastapi import FastAPI
import requests
import json

app = FastAPI()
COMFY_API_URL = "http://127.0.0.1:8188/prompt"

@app.post("/create-reel")
async def create_reel(script: str, property_img: str, model_img: str):
    # 1. Generate Voice with Svara
    # generate_svara_audio(script)
    
    # 2. Load the ComfyUI Workflow JSON
    with open("workflows/reel_config.json", "r") as f:
        workflow = json.load(f)
    
    # 3. Inject inputs (images and script)
    # workflow["node_id"]["inputs"]["image"] = property_img
    
    # 4. Push to ComfyUI
    response = requests.post(COMFY_API_URL, json={"prompt": workflow})
    return response.json()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
