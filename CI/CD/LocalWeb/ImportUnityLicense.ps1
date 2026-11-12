param(
    [Parameter(Mandatory = $true)]
    [string]$LicensePath
)

$ErrorActionPreference = "Stop"
$resolvedLicense = (Resolve-Path -LiteralPath $LicensePath).Path
if ([System.IO.Path]::GetExtension($resolvedLicense) -ne ".ulf") {
    throw "Unity 라이선스 파일(.ulf)만 가져올 수 있습니다."
}

$composePath = Join-Path $PSScriptRoot "compose.yaml"
docker compose -f $composePath cp $resolvedLicense "local-web:/tmp/Unity_lic.ulf"
if ($LASTEXITCODE -ne 0) {
    throw "Unity 라이선스 파일을 Docker 컨테이너로 복사하지 못했습니다."
}

docker compose -f $composePath exec -T --user root local-web sh -lc `
    'install -d -o mainflow -g mainflow -m 700 /home/mainflow/.local/share/unity3d/Unity && install -o mainflow -g mainflow -m 600 /tmp/Unity_lic.ulf /home/mainflow/.local/share/unity3d/Unity/Unity_lic.ulf && rm -f /tmp/Unity_lic.ulf'
if ($LASTEXITCODE -ne 0) {
    throw "Unity 라이선스를 전용 Docker Volume에 설치하지 못했습니다."
}

Write-Host "Unity 라이선스를 main-flow-chart-unity-license Volume에 등록했습니다."
