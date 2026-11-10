import os
import google.generativeai as genai

api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    raise ValueError("GEMINI_API_KEY environment variable not found")

genai.configure(api_key=api_key)

# Using official standard 2.0 flash model
model = genai.GenerativeModel("gemini-2.0-flash")

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
    f.write(response.text
