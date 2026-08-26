@echo off
setlocal EnableExtensions DisableDelayedExpansion

echo WARNING:
echo This is the Research worktree.
echo The current GUI does NOT expose TASK-021A Global Path.
echo Use run_research_global_path.bat for Global Path research.
echo.
call "%~dp0run_research_gui.bat" %*
exit /b %ERRORLEVEL%
