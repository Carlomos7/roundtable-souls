pragma ComponentBehavior: Bound
import QtQuick
import Theme

// The focus ring (v2.5 D / E): 2 px accent, 2 px outside the control, keyboard only. Make it a child of the control
// (it fills the parent and grows outwards) and bind `active` to the control's `visualFocus` (true for Tab, Backtab
// and shortcut focus, never for a mouse click). Text inputs bind `activeFocus` instead: the border on focus marks
// where typing goes (v2.5 D "border only on focus"). `error` turns the ring red (statusDanger).
Rectangle {
    id: root

    property bool active: false
    property bool error: false
    property real radiusOf: Theme.radiusControl
    property color ringColor: error ? Theme.statusDanger : Theme.accent

    anchors.fill: parent
    anchors.margins: -(Theme.focusRingW + Theme.focusRingGap)
    border.color: ringColor
    border.width: Theme.focusRingW
    color: "transparent"
    opacity: active || error ? 1 : 0
    radius: radiusOf + Theme.focusRingW + Theme.focusRingGap
    visible: opacity > 0
    z: 10

    Behavior on border.color {
        ColorAnimation {
            duration: Theme.mFast
            easing.type: Easing.OutCubic
        }
    }
    Behavior on opacity {
        NumberAnimation {
            duration: Theme.mFast
            easing.type: Easing.OutCubic
        }
    }
}
