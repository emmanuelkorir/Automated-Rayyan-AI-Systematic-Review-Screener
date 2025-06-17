import os
import dotenv

# Load environment variables from .env file
dotenv.load_dotenv()

from google import genai

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

response = client.models.generate_content(
    model="gemini-2.5-flash-preview-05-20", contents="Explain how AI works in a few words"
)
print(response.text)