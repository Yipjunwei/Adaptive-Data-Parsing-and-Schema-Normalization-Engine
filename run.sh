python3.11 -m venv .venv
source .venv/bin/activate
python --version
pip install -r requirements.txt
export GEMINI_API_KEY=put_your_api_key_here
python -m uvicorn app.main:app --reload