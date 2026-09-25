@echo off
setlocal

rem Starts both development servers in separate windows.
rem Stop them with Ctrl+C in each server window, or close both windows.

set "PROJECT_ROOT=%~dp0"
set "BACKEND_DIR=%PROJECT_ROOT%backend"
set "FRONTEND_DIR=%PROJECT_ROOT%frontend"

where uv >nul 2>&1
if errorlevel 1 (
  echo [ERROR] uv was not found on PATH. Install uv and reopen this launcher.
  pause
  exit /b 1
)

where npm >nul 2>&1
if errorlevel 1 (
  echo [ERROR] npm was not found on PATH. Install Node.js and reopen this launcher.
  pause
  exit /b 1
)

if not exist "%BACKEND_DIR%\" (
  echo [ERROR] Backend directory not found: "%BACKEND_DIR%"
  pause
  exit /b 1
)

if not exist "%BACKEND_DIR%\pyproject.toml" (
  echo [ERROR] Missing backend project file: "%BACKEND_DIR%\pyproject.toml"
  pause
  exit /b 1
)

if not exist "%BACKEND_DIR%\uv.lock" (
  echo [ERROR] Missing backend lock file: "%BACKEND_DIR%\uv.lock"
  pause
  exit /b 1
)

if not exist "%BACKEND_DIR%\main.py" (
  echo [ERROR] Missing backend entrypoint: "%BACKEND_DIR%\main.py"
  pause
  exit /b 1
)

if not exist "%FRONTEND_DIR%\" (
  echo [ERROR] Frontend directory not found: "%FRONTEND_DIR%"
  pause
  exit /b 1
)

if not exist "%FRONTEND_DIR%\package.json" (
  echo [ERROR] Missing frontend project file: "%FRONTEND_DIR%\package.json"
  pause
  exit /b 1
)

start "RAG Chatbot - Backend" cmd /k "cd /d ""%BACKEND_DIR%"" && uv run uvicorn main:app --reload"
start "RAG Chatbot - Frontend" cmd /k "cd /d ""%FRONTEND_DIR%"" && npm run dev"

echo Development servers opened in separate windows.
echo Press Ctrl+C in each server window to stop it.
endlocal
