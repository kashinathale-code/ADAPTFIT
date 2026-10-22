# run_live.ps1 - Launch ADAPTFIT with all live external data flags enabled
$env:USE_LIVE_RAINFALL = "true"
$env:USE_LIVE_SLOPE = "true"
$env:USE_LIVE_SOIL = "true"
$env:USE_LIVE_OSM = "true"

Write-Host "ADAPTFIT: Live data flags enabled (Rainfall, Slope, Soil, OSM)." -ForegroundColor Green
python app.py
