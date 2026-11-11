# ==============================================================================
# PowerShell Runner for SDN-Based Adaptive Load Balancer on Windows
# ==============================================================================

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " Launching SDN Adaptive Load Balancer on Windows Terminal" -ForegroundColor Yellow
Write-Host "==========================================================" -ForegroundColor Cyan

$env:PYTHONPATH = ".;$env:PYTHONPATH"
python run_windows.py
