pragma ComponentBehavior: Bound
import QtQuick
import Theme
import App

// The gilded surface used by every primary button and every "selected / current" control (v2.9, v2.10): a faint
// vertical accent wash, a 1 px accent outline, a 1 px top sheen; on `hot` (hover) the wash and outline brighten and a
// thin halo (see below) lights the edge. `inner` adds the game's second frame line 3 px in (Launch). `glow` keeps a faint resting
// glow (Launch). Light theme: the same roles in Carian blue.
Item {
    id: root

    property bool hot: false
    property bool inner: false
    property bool glow: false
    property bool dim: false            // blocked / disabled: a plain edge outline, no wash, no glow
    property bool pressed: false        // the wash goes flat and the halo collapses for the press
    property int radius: Theme.radiusControl

    // The halo (v2.12, reined in): a luminous EDGE, not a bloom. 1 px rings just outside the outline, alpha falling
    // off with the square of the distance, 3 px at rest (Launch only) and 6 px on hover; none on press, Reduced or
    // Off. The old version stacked three filled rectangles 12-18 px out, which read as a smudge around the button.
    readonly property int haloPx: dim || pressed || AppState.effects !== "full" ? 0 : hot ? Theme.glowHaloHover : glow ? Theme.glowHaloRest : 0
    readonly property real haloPeak: hot ? Theme.glowSoft.a : Theme.glowRest.a

    Repeater {
        model: 6

        Rectangle {
            id: ring

            required property int index
            readonly property real falloff: root.haloPx > 0 && index < root.haloPx ? Math.pow(1 - index / root.haloPx, 2) : 0

            anchors.fill: parent
            anchors.margins: -(index + 1)
            border.color: Theme.glowColor
            border.width: 1
            color: "transparent"
            opacity: root.haloPeak * ring.falloff
            radius: root.radius + index + 1
            visible: opacity > 0.004

            Behavior on opacity {
                NumberAnimation {
                    duration: Theme.mFast
                    easing.type: Easing.OutCubic
                }
            }
        }
    }
    Rectangle {
        anchors.fill: parent
        border.color: root.dim ? Theme.borderEdge : root.hot ? Theme.goldLineHover : Theme.goldLine
        border.width: 1
        radius: root.radius

        gradient: Gradient {
            GradientStop {
                color: root.dim ? "transparent" : root.pressed ? Theme.goldFillBottomHover : root.hot ? Theme.goldFillTopHover : Theme.goldFillTop
                position: 0
            }
            GradientStop {
                color: root.dim ? "transparent" : root.pressed ? Theme.goldFillBottomHover : root.hot ? Theme.goldFillBottomHover : Theme.goldFillBottom
                position: 1
            }
        }

        Behavior on border.color {
            ColorAnimation {
                duration: Theme.mFast
                easing.type: Easing.OutCubic
            }
        }
    }
    Rectangle {  // the top sheen
        anchors.left: parent.left
        anchors.leftMargin: root.radius
        anchors.right: parent.right
        anchors.rightMargin: root.radius
        anchors.top: parent.top
        anchors.topMargin: 1
        color: Theme.goldSheen
        height: 1
        visible: !root.dim
    }
    Rectangle {  // the inner frame line (the game's double frame)
        anchors.fill: parent
        anchors.margins: 3
        border.color: Theme.goldInner
        border.width: 1
        color: "transparent"
        radius: Math.max(1, root.radius - 3)
        visible: root.inner && !root.dim
    }
}
