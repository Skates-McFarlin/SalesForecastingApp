@echo off
SET SCRIPT_DIR=%~dp0
powershell -Command "Start-Process powershell -ArgumentList '-ExecutionPolicy Bypass -File \"%SCRIPT_DIR%setup-backend.ps1\"' -Verb RunAs"