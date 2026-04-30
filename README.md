# Tour Booking Chatbot Backend

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
```

## Railway
Set env vars from `.env.example`, then run start command:

```bash
uvicorn app.main:app --host 0.0.0.0 --port ${PORT}
```
