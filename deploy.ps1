# JARVIS GitHub Pages 배포 스크립트
# 사용법: JARVIS_배포.bat 더블클릭 (또는 이 파일 우클릭 → PowerShell로 실행)
$ErrorActionPreference = 'Continue'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here

Write-Host ""
Write-Host "  ═══ J.A.R.V.I.S. GitHub Pages 배포 ═══" -ForegroundColor Cyan
Write-Host ""

# 1) GitHub CLI 확인
$ghExe = "gh"
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    $candidates = @(
        "$env:LOCALAPPDATA\Programs\GitHubCLI\bin\gh.exe",
        "$env:ProgramFiles\GitHub CLI\gh.exe"
    )
    $ghPath = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($ghPath) { $ghExe = $ghPath }
    else {
        Write-Host "GitHub CLI가 설치되어 있지 않습니다. 설치를 시작합니다..." -ForegroundColor Yellow
        winget install --id GitHub.cli -e --accept-source-agreements --accept-package-agreements
        Write-Host ""
        Write-Host "설치 완료. 이 창을 닫고 JARVIS_배포.bat 을 다시 실행해주세요." -ForegroundColor Green
        Read-Host "엔터를 누르면 종료합니다"
        exit
    }
}

# 2) 로그인 확인 (없으면 브라우저 로그인 진행)
& $ghExe auth status 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "GitHub 로그인이 필요합니다. 안내에 따라 진행해주세요." -ForegroundColor Yellow
    Write-Host "(엔터를 누르면 브라우저가 열립니다. 계정이 없다면 github.com 에서 무료 가입 후 다시 실행)" -ForegroundColor DarkGray
    & $ghExe auth login --hostname github.com --git-protocol https --web
    & $ghExe auth status 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "로그인이 완료되지 않았습니다. 다시 실행해주세요." -ForegroundColor Red
        Read-Host "엔터를 누르면 종료합니다"
        exit
    }
}

$user = & $ghExe api user -q .login
Write-Host "로그인 계정: $user" -ForegroundColor Green

# 3) git 저장소 준비 및 푸시
if (-not (Test-Path ".git")) { git init -b main | Out-Null }
git add index.html
git -c user.name="$user" -c user.email="$user@users.noreply.github.com" commit -m "JARVIS deploy" 2>$null

& $ghExe repo view "$user/jarvis" 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "저장소 생성 중..." -ForegroundColor Cyan
    & $ghExe repo create jarvis --public --source . --push
} else {
    git remote get-url origin 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { git remote add origin "https://github.com/$user/jarvis.git" }
    git push -u origin main
}

# 4) GitHub Pages 활성화 (이미 켜져 있으면 무시)
& $ghExe api -X POST "repos/$user/jarvis/pages" -f "source[branch]=main" -f "source[path]=/" 2>$null | Out-Null

Write-Host ""
Write-Host "  ══════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  배포 완료! 1~2분 뒤 아래 주소로 접속하세요:" -ForegroundColor Green
Write-Host ""
Write-Host "  https://$user.github.io/jarvis/" -ForegroundColor Cyan
Write-Host ""
Write-Host "  이 주소는 어떤 컴퓨터, 휴대폰에서든 열립니다." -ForegroundColor DarkGray
Write-Host "  (자비스 파일을 수정한 뒤에는 이 배포 파일을 다시 실행하면 갱신됩니다)" -ForegroundColor DarkGray
Write-Host "  ══════════════════════════════════════════════" -ForegroundColor Cyan
Read-Host "엔터를 누르면 종료합니다"
