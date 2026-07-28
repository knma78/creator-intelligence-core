@echo off
chcp 65001 >nul
title Content Research 程序控制台
set "ROOT=%~dp0"
if not exist "%ROOT%tools\ContentResearch-Control.ps1" (
  echo [错误] 找不到控制脚本：%ROOT%tools\ContentResearch-Control.ps1
  echo 请确认项目目录完整，或重新创建桌面快捷方式。
  pause
  exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%ROOT%tools\ContentResearch-Control.ps1" -Action menu
if errorlevel 1 (
  echo.
  echo [错误] 控制台异常退出，请查看项目 logs 目录。
  pause
)
