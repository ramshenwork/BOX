# CricketLive Scorer

A full-stack cricket scoring web app built with FastAPI + responsive HTML/CSS/JS.

## Run Locally

```bash
pip install -r requirements.txt
python main.py
```
Open: http://localhost:8000

## Deploy to Render (Free)

1. Push this folder to a GitHub repo
2. Go to https://render.com → New Web Service
3. Connect your GitHub repo
4. Settings:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
5. Click Deploy!

## Deploy to Railway

1. Push to GitHub
2. Go to https://railway.app → New Project → Deploy from GitHub
3. Add variable: `PORT=8000`
4. Railway auto-detects Python and deploys

## Features

- 📱 Mobile + Desktop responsive UI (auto-detects, toggle manually)
- 🏏 Full match setup: teams, players, overs, JOKER player
- 🪙 Coin toss (odd/even)
- ⚡ Live scoring: 1, 2, 3, 4, 6, NB (leg), NB (height), WD, W (bowled/runout/caught)
- 📊 Live batting stats: Runs, Balls, SR, 4s, 6s
- 📊 Live bowling stats: Overs, Wickets, Runs, Economy, Extras
- 📉 Fall of Wickets tracker
- 🎯 2nd innings: Target, RRR, Balls needed display
- DNB (Did Not Bat) tracking
- ↩ Undo last ball
