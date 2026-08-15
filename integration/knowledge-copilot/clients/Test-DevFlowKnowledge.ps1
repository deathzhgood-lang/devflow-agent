param(
    [Parameter(Mandatory = $true)][string]$Origin,
    [string]$TenantId = "local-demo",
    [string]$UserId = "devflow-integration",
    [string[]]$Groups = @("engineering"),
    [int]$TopK = 3
)

$ErrorActionPreference = "Stop"
$Origin = $Origin.TrimEnd("/")
$token = $env:KNOWLEDGE_SERVICE_TOKEN
if (-not $token) {
    $secureToken = Read-Host "Knowledge Service Token" -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureToken)
    try {
        $token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
}
if (-not $token) { throw "Knowledge Service Token is required." }

$health = Invoke-RestMethod -Uri "$Origin/health" -TimeoutSec 10
$requestId = "devflow-smoke-$([guid]::NewGuid().ToString('N'))"
$body = @{
    query = "登录接口返回 401 时应该如何排查？"
    tenant_id = $TenantId
    user_id = $UserId
    groups = $Groups
    filters = @{ service = $null; document_types = @(); tags = @() }
    top_k = $TopK
    request_id = $requestId
} | ConvertTo-Json -Depth 6

$result = Invoke-RestMethod -Uri "$Origin/api/v1/retrieval/query" -Method Post `
    -Headers @{ Authorization = "Bearer $token"; "X-Request-ID" = $requestId } `
    -ContentType "application/json" -Body $body -TimeoutSec 45

$citationValid = @($result.evidence | Where-Object { $_.source_uri -notmatch '^knowledge://[^#]+#chunk=.+$' }).Count -eq 0
$untrustedValid = @($result.evidence | Where-Object { $_.metadata.untrusted_retrieved_content -ne $true }).Count -eq 0

[PSCustomObject]@{
    Health = $health.status
    RetrievalReady = $health.retrieval_ready
    RequestIdMatched = $result.request_id -eq $requestId
    TenantMatched = $result.tenant_id -eq $TenantId
    EvidenceCount = @($result.evidence).Count
    CitationContractValid = $citationValid
    UntrustedMarkerValid = $untrustedValid
    LatencyMs = $result.latency_ms
} | Format-List

if ($health.status -ne "ok" -or -not $citationValid -or -not $untrustedValid) {
    throw "DevFlow knowledge integration smoke test failed."
}

