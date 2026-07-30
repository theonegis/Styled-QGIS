$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $PSScriptRoot
$BuildDir = if ($args.Count -gt 0) {
    $args[0]
} else {
    Join-Path $ProjectDir "build-style"
}
$QlementineTag = if ($env:QLEMENTINE_TAG) {
    $env:QLEMENTINE_TAG
} else {
    "v1.4.2"
}

cmake -S $ProjectDir -B $BuildDir -G Ninja `
    -D CMAKE_BUILD_TYPE=Release `
    -D QGISPLUS_QLEMENTINE_TAG=$QlementineTag
cmake --build $BuildDir --config Release
ctest --test-dir $BuildDir -C Release --output-on-failure
cmake --install $BuildDir --config Release --prefix "$BuildDir/stage"

Write-Host "Style plugin: $BuildDir/stage/styles"

