pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Effects

// The GPU drop shadow (Qt 6.9+ RectangularShadow). Loaded by SoftShadow through a Loader so that on an older Qt
// (Design Studio 4.8 ships 6.8) the type's absence only fails this file and SoftShadow falls back to its rings.
RectangularShadow {
    property int blurPx: 3
    property color shadowColor: "black"
    property real cornerRadius: 0

    anchors.fill: parent
    blur: blurPx
    color: shadowColor
    offset: Qt.vector2d(0, 0)
    radius: cornerRadius
    spread: 0
}
