import os, base64
from dotenv import load_dotenv
from mistralai.client import Mistral
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))
c = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
r = c.audio.speech.complete(input="Inspection Forecaster. Can AI predict a restaurant's health grade?", model="voxtral-mini-tts-latest", voice_id="c69964a6-ab8b-4f8a-9465-ec0925096ec8", response_format="mp3")
open("tts_test.mp3","wb").write(base64.b64decode(r.audio_data))
