$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$version = "8.21.0"
$archiveSha256 = "aa1b66a70eace83dc624508745646c08ae561de512ab403adffb93ac87fc72e6"
$prefix = if ($env:PYNETFT_CURL_PREFIX) { $env:PYNETFT_CURL_PREFIX } else { "C:\pynetft-curl" }
$buildRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("pynetft-curl-" + [guid]::NewGuid())
$archive = if ($env:PYNETFT_CURL_ARCHIVE_CACHE) {
    $env:PYNETFT_CURL_ARCHIVE_CACHE
} else {
    Join-Path $buildRoot "curl-$version.tar.xz"
}
$sourceRoot = Join-Path $buildRoot "source"
$binaryRoot = Join-Path $buildRoot "build"

function Get-Sha256([string] $path) {
    $algorithm = [System.Security.Cryptography.SHA256]::Create()
    $stream = [System.IO.File]::OpenRead($path)
    try {
        return ([System.BitConverter]::ToString($algorithm.ComputeHash($stream))).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $stream.Dispose()
        $algorithm.Dispose()
    }
}

$vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
if (-not (Test-Path -LiteralPath $vswhere -PathType Leaf)) {
    throw "unable to locate vswhere.exe"
}
$visualStudioVersion = (
    & $vswhere -latest -products * `
        -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
        -property installationVersion
).Trim()
if ($LASTEXITCODE -ne 0 -or -not $visualStudioVersion) {
    throw "unable to locate a Visual Studio C++ toolchain"
}
$visualStudioGenerator = if ($visualStudioVersion.StartsWith("18.")) {
    "Visual Studio 18 2026"
} elseif ($visualStudioVersion.StartsWith("17.")) {
    "Visual Studio 17 2022"
} else {
    throw "unsupported Visual Studio version: $visualStudioVersion"
}

try {
    New-Item -ItemType Directory -Force -Path $buildRoot, $sourceRoot | Out-Null
    if (-not (Test-Path -LiteralPath $archive -PathType Leaf)) {
        Invoke-WebRequest "https://curl.se/download/curl-$version.tar.xz" -OutFile $archive
    }
    $actualSha256 = Get-Sha256 $archive
    if ($actualSha256 -ne $archiveSha256) {
        throw "curl source archive checksum mismatch"
    }

    tar -xJf $archive --strip-components=1 -C $sourceRoot
    if ($LASTEXITCODE -ne 0) {
        throw "unable to extract curl source archive"
    }

    cmake -S $sourceRoot -B $binaryRoot -G $visualStudioGenerator -A x64 `
        -DCMAKE_INSTALL_PREFIX="$prefix" `
        -DBUILD_CURL_EXE=OFF `
        -DBUILD_SHARED_LIBS=OFF `
        -DBUILD_STATIC_LIBS=ON `
        -DBUILD_TESTING=OFF `
        -DHTTP_ONLY=ON `
        -DCURL_USE_SCHANNEL=OFF `
        -DCURL_USE_LIBPSL=OFF `
        -DCURL_ZLIB=OFF `
        -DCURL_BROTLI=OFF `
        -DCURL_ZSTD=OFF `
        -DUSE_LIBIDN2=OFF `
        -DUSE_NGHTTP2=OFF
    if ($LASTEXITCODE -ne 0) {
        throw "unable to configure curl"
    }
    cmake --build $binaryRoot --config Release --parallel 2
    if ($LASTEXITCODE -ne 0) {
        throw "unable to build curl"
    }
    cmake --install $binaryRoot --config Release
    if ($LASTEXITCODE -ne 0) {
        throw "unable to install curl"
    }

    $staticLibrary = Join-Path $prefix "lib\libcurl.lib"
    if (-not (Test-Path -LiteralPath $staticLibrary -PathType Leaf)) {
        throw "curl static library was not installed"
    }
    if (Get-ChildItem -LiteralPath $prefix -Recurse -Filter "libcurl.dll") {
        throw "curl shared library was unexpectedly installed"
    }
}
finally {
    if (Test-Path -LiteralPath $buildRoot) {
        Remove-Item -LiteralPath $buildRoot -Recurse -Force
    }
}
