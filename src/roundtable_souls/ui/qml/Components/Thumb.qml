pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.impl
import Theme

// A small picture for a picker row (v2.15): `source` is the game exe's icon (image://gameicon/..., a bitmap shown as
// is) or an SVG emblem (tinted like an icon); `fallback` is the emblem shown when a bitmap cannot load.
Rectangle {
    id: root

    property url fallback
    property int size: 24
    property url source

    readonly property bool vector: String(source).toLowerCase().endsWith(".svg")   // an emblem: tinted like an icon
    readonly property bool showBitmap: !vector && bitmap.status === Image.Ready

    color: showBitmap ? "transparent" : Theme.fillIdentity
    height: size
    radius: Theme.radiusControl
    width: size

    Image {
        id: bitmap

        anchors.fill: parent
        asynchronous: true
        fillMode: Image.PreserveAspectFit
        smooth: true
        source: root.vector ? "" : root.source
        sourceSize: Qt.size(root.size * 2, root.size * 2)   // 2x for 200 % displays
        visible: root.showBitmap
    }
    IconImage {
        anchors.centerIn: parent
        color: Theme.textIcon
        height: Math.round(root.size * 0.7)
        source: root.vector ? root.source : root.fallback
        sourceSize: Qt.size(height, height)
        visible: root.vector || (!root.showBitmap && String(root.fallback).length > 0)
        width: height
    }
}
