# 매일 오전 9시, 로그인된 현재 사용자로 실행한다. 비밀번호는 저장하지 않는다.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$batchPath = Join-Path $projectRoot 'run-menu-keywords.bat'
$taskName = 'BrandAnalyze-MenuKeywords-Daily'
if ((Get-TimeZone).Id -ne 'Korea Standard Time') {
    throw 'Windows 시간대를 한국 표준시로 설정한 뒤 등록하세요.'
}
if (-not (Test-Path -LiteralPath $batchPath)) { throw 'BAT 파일이 없습니다.' }
$action = New-ScheduledTaskAction -Execute $env:ComSpec -Argument ('/d /c ""{0}""' -f $batchPath) -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger -Daily -At '09:00'
$principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description '매장 키워드 수집, 분석, LLM 요약 및 Gmail 발송. 매일 한국 시간 09:00.' -Force | Select-Object TaskName,State
