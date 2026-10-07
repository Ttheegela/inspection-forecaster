"""Narration per scene -> video/audio/NN.mp3 via Mistral Voxtral TTS (fallback: macOS say)."""
import os, base64, subprocess
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
from mistralai.client import Mistral

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "audio"); os.makedirs(OUT, exist_ok=True)
load_dotenv(os.path.join(HERE, "..", ".env"))
VOICE = "c69964a6-ab8b-4f8a-9465-ec0925096ec8"  # preset en_paul_neutral

SCRIPT = {
"01": "In New York, a C grade in the window can sink a restaurant. Inspection Forecaster asks a simple question: can an AI agent predict that grade before the inspector walks in? We built it at the Elastic and Mistral NYC Hack Night.",
"02": "We load NYC Open Data, health inspections and 311 complaints, into Elasticsearch. Violation text is a semantic text field, embedded by Mistral inside Elastic. A Mistral Large 4 agent calls four tools: inspection history, nearby complaints by geo distance, zip code baselines, and semantic search for restaurants with similar violations. Every tool only sees data dated before the inspection, so the model can't peek at the answer.",
"03": "Here's a real run. Guiz Hou Miao Jia Noodles in Flushing, as of June fifteenth. The agent finds one prior inspection, scored 25. It finds four 311 complaints within 75 meters, including food poisoning reported just eight days earlier. Then it checks the zip code and searches for restaurants with similar temperature violations.",
"04": "Its verdict: a C, score around 30, citing temperature abuse, no pest control contract, and that recent complaint. The actual inspection? A C, with a score of 55.",
"05": "Then we backtested it honestly. Version one lost to a naive baseline. It assumed restaurants improve after a bad inspection, and caught zero percent of C restaurants. So we added a calibration rule, anchor on the last score, and re-tested on a fresh held-out sample. Version two catches 9 of 10 C restaurants, versus 1 of 10 for same grade as last time, and 8 of 10 for last score to band.",
"06": "The trade-off is real. Overall accuracy is 43 percent, versus 47 for the best baseline, because version two over-flags A restaurants. Every forecast is stored in Elastic, and this breakdown comes straight from an ES|QL query.",
"07": "The 311 data is geo-indexed, too. Thousands of complaints across the city: rodents, food poisoning, food establishments. The agent queries them by distance and date.",
"08": "In Kibana, an Agent Builder agent running on Mistral Medium answers questions over the same data, with five ES|QL tools and semantic search. Ask which C restaurants the forecaster caught, and it queries the forecasts index directly.",
"09": "The takeaway: this agent is a strong early warning system for C restaurants, but not yet a better all-round predictor. Next up: a bigger backtest, better calibration on A restaurants, and matching complaints to the restaurant itself. The code is on GitHub. Thanks for watching.",
}


def speak(k):
    path = os.path.join(OUT, f"{k}.mp3")
    try:
        c = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
        r = c.audio.speech.complete(input=SCRIPT[k], model="voxtral-mini-tts-latest", voice_id=VOICE, response_format="mp3")
        open(path, "wb").write(base64.b64decode(r.audio_data)); return k, "voxtral"
    except Exception as e:
        print(k, "voxtral failed:", repr(e)[:200])
        aiff = path.replace(".mp3", ".aiff")
        subprocess.run(["say", "-v", "Samantha", "-o", aiff, SCRIPT[k]], check=True)
        subprocess.run(["/opt/homebrew/bin/ffmpeg", "-y", "-loglevel", "error", "-i", aiff, path], check=True)
        return k, "say"


if __name__ == "__main__":
    print("words:", sum(len(v.split()) for v in SCRIPT.values()))
    with ThreadPoolExecutor(5) as ex:
        print(list(ex.map(speak, SCRIPT)))
