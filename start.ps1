[CmdletBinding()]
param(
    [ValidateSet('selftest', 'school-preview', 'capture-group', 'baseline', 'once', 'run')]
    [string]$Mode = 'selftest',
    [string]$PythonPath = 'C:\Users\liuay\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
)

$ErrorActionPreference = 'Stop'
$requiredNames = switch ($Mode) {
    'school-preview' { @('SDUT_USER', 'SDUT_PWD') }
    'baseline' { @('SDUT_USER', 'SDUT_PWD') }
    'capture-group' { @('QQ_APPID', 'QQ_SECRET') }
    'once' { @('SDUT_USER', 'SDUT_PWD', 'QQ_APPID', 'QQ_SECRET', 'QQ_GROUP_OPENID') }
    'run' { @('SDUT_USER', 'SDUT_PWD', 'QQ_APPID', 'QQ_SECRET', 'QQ_GROUP_OPENID') }
    default { @() }
}
$previousValues = @{}
$pythonExit = 1
Push-Location -LiteralPath $PSScriptRoot
try {
    if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
        throw 'Python executable was not found. Specify -PythonPath with your Python executable.'
    }
    foreach ($configName in @('PYTHONUTF8') + @($requiredNames)) {
        $previousValues[$configName] = [Environment]::GetEnvironmentVariable($configName, 'Process')
    }
    [Environment]::SetEnvironmentVariable('PYTHONUTF8', '1', 'Process')
    foreach ($configName in $requiredNames) {
        if ([Environment]::GetEnvironmentVariable($configName, 'Process')) { continue }
        $configValue = $null
        if ($configName -in @('SDUT_PWD', 'QQ_SECRET')) {
            $protectedValue = Read-Host "$configName (hidden input, not saved to disk)" -AsSecureString
            $valuePointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($protectedValue)
            try {
                $configValue = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($valuePointer)
            } finally {
                [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($valuePointer)
                $protectedValue.Dispose()
            }
        } else {
            $configValue = Read-Host $configName
        }
        if ([string]::IsNullOrWhiteSpace($configValue)) { throw "$configName must not be empty." }
        [Environment]::SetEnvironmentVariable($configName, $configValue, 'Process')
        $configValue = $null
    }
    switch ($Mode) {
        'school-preview' { & $PythonPath sync_qqbot.py --dry-run }
        'baseline' { & $PythonPath sync_qqbot.py --baseline }
        'capture-group' { & $PythonPath get_group_openid.py }
        'once' { & $PythonPath sync_qqbot.py --once }
        'run' { & $PythonPath sync_qqbot.py }
        default { & $PythonPath sync_qqbot.py --selftest }
    }
    $pythonExit = $LASTEXITCODE
} finally {
    foreach ($configName in $previousValues.Keys) {
        if ($null -eq $previousValues[$configName]) {
            Remove-Item -LiteralPath "Env:$configName" -ErrorAction SilentlyContinue
        } else {
            [Environment]::SetEnvironmentVariable($configName, $previousValues[$configName], 'Process')
        }
    }
    Pop-Location
}
exit $pythonExit
