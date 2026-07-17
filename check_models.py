import httpx
import os
from dotenv import load_dotenv

# Load your GEMINI_API_KEY from the .env file
load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    print("Error: GEMINI_API_KEY not found in .env file.")
    exit()

print("Fetching available models...\n")

# Google's endpoint to list all accessible models
url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"

with httpx.Client() as client:
    response = client.get(url)
    
    if response.status_code == 200:
        models = response.json().get("models", [])
        print("✅ Your API key has access to the following models:\n")
        
        for model in models:
            # We only want to see the model names, filtering out embedding models for clarity
            name = model.get("name")
            if "gemini" in name:
                print(f" - {name.replace('models/', '')}")
    else:
        print(f"❌ Failed to fetch models. Status code: {response.status_code}")
        print(response.text)