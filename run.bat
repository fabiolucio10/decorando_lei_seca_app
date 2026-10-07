@echo off
chcp 65001 >nul
python -m streamlit run app.py
if %ERRORLEVEL% NEQ 0 (
    py -m streamlit run app.py
)
if %ERRORLEVEL% NEQ 0 (
    streamlit run app.py
)
pause
