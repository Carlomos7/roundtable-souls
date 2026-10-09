pragma ComponentBehavior: Bound
import QtQuick
import Theme

// The game's hover / selection highlight (v2.8): a soft horizontal streak of light behind a row, brightest about a
// third of the way in, fading to nothing at both ends. Not a filled box. `strength` 0..1 animates it in.
Rectangle {
    id: root

    property color tint: Theme.smearHover
    property real strength: 0
    property real peak: 0.32

    color: "transparent"
    opacity: strength

    gradient: Gradient {
        orientation: Gradient.Horizontal

        GradientStop { position: 0.0; color: Qt.rgba(root.tint.r, root.tint.g, root.tint.b, 0) }
        GradientStop { position: Math.max(0.05, root.peak - 0.22); color: Qt.rgba(root.tint.r, root.tint.g, root.tint.b, root.tint.a * 0.7) }
        GradientStop { position: root.peak; color: root.tint }
        GradientStop { position: Math.min(0.95, root.peak + 0.4); color: Qt.rgba(root.tint.r, root.tint.g, root.tint.b, root.tint.a * 0.35) }
        GradientStop { position: 1.0; color: Qt.rgba(root.tint.r, root.tint.g, root.tint.b, 0) }
    }

    Behavior on opacity {
        NumberAnimation {
            duration: Theme.mFast
            easing.type: Easing.OutCubic
        }
    }
}
