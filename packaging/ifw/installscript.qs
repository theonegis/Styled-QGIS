function Component() {
}

Component.prototype.createOperations = function() {
    component.createOperations();

    if (systemInfo.productType === "windows") {
        component.addOperation(
            "CreateShortcut",
            "@TargetDir@/bin/QGIS+.exe",
            "@StartMenuDir@/QGIS+.lnk"
        );
    }
}
