@echo off
rem AeroXProtect launcher CLI wrapper — run from anywhere (admin terminal):
rem   C:\AeroXProtect\launcher\axpctl status | logs <svc> [n] | restart <svc>
rem                            | update-check | update-apply [ver] | stop
setlocal
set "AXP_HOME=%~dp0.."
set "PYTHONPATH=%~dp0"
"%~dp0..\runtime\python\python.exe" -m axp_launcher.ctl %*
