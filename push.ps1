param(
    [string]$Tag = "latest"
)

$ErrorActionPreference = "Stop"

# Image / container config
$ImageName = "obviousviking/artillery_2"
$ContainerName = "artillery_2"
$HostDataPath = "C:\Users\Ramsk\OneDrive\Desktop\artillery_2_data"
$HostDownloadsPath = "C:\Users\Ramsk\OneDrive\Desktop\artillery_2_downloads"
$HostPort = 5000
$ContainerPort = 5000

Write-Host "==> Building image: ${ImageName}:$Tag"
docker build -t "${ImageName}:$Tag" .

if ($LASTEXITCODE -ne 0) {
    Write-Error "Docker build failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}

if ($Tag -ne "latest") {
    Write-Host "==> Tagging ${ImageName}:$Tag as ${ImageName}:latest"
    docker tag "${ImageName}:$Tag" "${ImageName}:latest"
}

Write-Host "==> Pushing ${ImageName}:$Tag"
docker push "${ImageName}:$Tag"

if ($LASTEXITCODE -ne 0) {
    Write-Error "Docker push failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}

if ($Tag -ne "latest") {
    Write-Host "==> Pushing ${ImageName}:latest"
    docker push "${ImageName}:latest"
}

Write-Host "==> Push complete."

# --- Local update / redeploy ---

Write-Host "==> Ensuring host data directory exists at $HostDataPath"
if (-not (Test-Path $HostDataPath)) {
    New-Item -ItemType Directory -Path $HostDataPath | Out-Null
}

Write-Host "==> Ensuring host downloads directory exists at $HostDownloadsPath"
if (-not (Test-Path $HostDownloadsPath)) {
    New-Item -ItemType Directory -Path $HostDownloadsPath | Out-Null
}

$FullImage = "${ImageName}:$Tag"

Write-Host "==> Pulling ${FullImage} (to sync with Docker Hub)"
docker pull $FullImage

Write-Host "==> Stopping existing container '$ContainerName' (if running)"
docker stop $ContainerName 2>$null | Out-Null

Write-Host "==> Removing existing container '$ContainerName' (if present)"
docker rm $ContainerName 2>$null | Out-Null

Write-Host "==> Starting new container '$ContainerName' from $FullImage"
docker run -d `
    --name $ContainerName `
    -p ${HostPort}:${ContainerPort} `
    -v "${HostDataPath}:/data" `
    -v "${HostDownloadsPath}:/downloads" `
    $FullImage | Out-Null


Write-Host "==> Done! Container '$ContainerName' is running on http://localhost:$HostPort"
