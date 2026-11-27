@echo off
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
python -m pilon demo
if errorlevel 1 (
    pause
    exit /b 1
)
start "" "runtime\ecommerce-facets.html"
