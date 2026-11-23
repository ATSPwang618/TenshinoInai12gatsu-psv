param(
    [string]$Source = '',
    [string]$Output = '',
    [string]$WorkDir = '',
    [string]$Wsl = '',
    [string]$Sdk = '',
    [string]$Ffmpeg = '',
    [string]$Ffprobe = '',
    [ValidateRange(1,32)][int]$Jobs = 4,
    [switch]$Check,
    [string]$Python = 'python'
)
$ErrorActionPreference = 'Stop'
$launcher = Join-Path $PSScriptRoot 'build-vita.py'
$forward = @('-X', 'utf8', $launcher, '--jobs', "$Jobs")
foreach($pair in @(
    @('--source', $Source), @('--output', $Output), @('--work-dir', $WorkDir),
    @('--wsl', $Wsl), @('--sdk', $Sdk), @('--ffmpeg', $Ffmpeg), @('--ffprobe', $Ffprobe)
)) {
    if($pair[1]) { $forward += @($pair[0], $pair[1]) }
}
if($Check) { $forward += '--check' }
& $Python @forward
exit $LASTEXITCODE
