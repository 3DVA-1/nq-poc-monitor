$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonCommand = Get-Command py -ErrorAction SilentlyContinue
if ($pythonCommand) {
    & py -3 -m pip install -r requirements.txt
    & py -3 monitor.py --dry-run
} else {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCommand) { throw 'Iš pradžių įdiek Python 3.12 arba naujesnį.' }
    & python -m pip install -r requirements.txt
    & python monitor.py --dry-run
}
Read-Host 'Paspausk Enter, kad uždarytum langą'
