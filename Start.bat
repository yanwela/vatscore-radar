@echo off
title VatScore Hybrid Radar Engine
echo [⚡] Igniting VatScore Backend Server...
start /min uvicorn backend:app --reload
echo [🛰️] Opening Premium User Interface...
timeout /t 2 >nul
start "" "index.html"
exit