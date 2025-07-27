@echo off
echo Building latest Artillery image...
docker build --no-cache -t artillery .

echo.
echo Starting Artillery container...

REM Set up paths for config, tasks, and downloads
set CONFIG_DIR=%cd%\host_config
set TASKS_DIR=%cd%\host_tasks
set DOWNLOADS_DIR=%cd%\host_downloads

docker run -it --rm ^
  -p 8080:8080 ^
  -v "%CONFIG_DIR%":/config ^
  -v "%TASKS_DIR%":/tasks ^
  -v "%DOWNLOADS_DIR%":/downloads ^
  artillery

pause

 