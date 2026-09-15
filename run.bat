\
@echo off
cd /d %~dp0

if not exist .venv (
  py -m venv .venv
)

call .venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

python -m uvicorn api.index:app --reload --host 127.0.0.1 --port 8000
