param(
    [ValidatePattern('^[0-9]{6}$')][string]$DemoCode = '482917',
    [ValidateRange(1024,65535)][int]$Port = 8000
)
$ErrorActionPreference = 'Stop'
if ($env:CAMPUS_MODE -eq 'production') {
    throw '当前终端为正式模式。请另开用于本地测试的终端，再运行演示启动脚本。'
}
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw '未找到项目虚拟环境，请先按 README 安装依赖。'
}
$env:CAMPUS_MODE = 'demo'
$env:CAMPUS_DEMO_CODE = $DemoCode
$env:FIN_WITHDRAW_DEMO_OUTCOME = 'succeeded'
Set-Location -LiteralPath $projectRoot
& $pythonPath (Join-Path $PSScriptRoot '准备演示账号.py')
if ($LASTEXITCODE -ne 0) { throw '准备演示账号失败，后端尚未启动。' }
& $pythonPath -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port $Port --reload
