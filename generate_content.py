import os
import google.generativeai as genai

api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    raise ValueError("GEMINI_API_KEY environment variable not found")

genai.configure(api_key=api_key)

# Automatically find an available text generation model
supported_model = "gemini-1.5-flash"
try:
    for m in genai.list_models():
        if "generateContent" in m.supported_generation_methods:
            if "gemini" in m.name:
                supported_model = m.name
                break
except Exception as e:
    print(f"Listing models failed: {e}")

print(f"Using model: {supported_model}")
model = genai.GenerativeModel(supported_model)

prompt = (
    "Generate 1 unique, engaging psychological concept or human behavior insight "
    "suitable for a silent animated stickman short video. "
    "Provide:\n"
    "1. Title\n"
    "2. Core Lesson (1 sentence)\n"
    "3. Scene-by-scene visual stickman animation ideas (no dialogue)\n"
    "4. Short on-screen captions"
)

response = model.generate_content(prompt)

print("=== MINDFORGE GENERATED CONTENT ===")
print(response.text)
print("===================================")

with open("latest_idea.txt", "w") as f:
    f.write(response.text)
