pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import Theme

// A checkbox (export list, repair findings). Off: 6% fill with a secondary-text outline (the box has to read as a
// box); on: accent, no outline. Keyboard focus shows the ring.
CheckBox {
    id: root

    focusPolicy: Qt.TabFocus
    font.family: Theme.fontFamily
    font.pixelSize: Theme.fontBody
    hoverEnabled: true
    spacing: Theme.gapStack

    contentItem: Txt {
        color: root.enabled ? Theme.textPrimary : Theme.textDisabled
        leftPadding: root.indicator.width + root.spacing
        text: root.text
    }
    indicator: Rectangle {
        border.color: Theme.textSecondary
        border.width: root.checked ? 0 : 1
        color: root.checked ? Theme.accent : root.hovered ? Theme.fillGhostHover : Theme.fillInput
        implicitHeight: 20
        implicitWidth: 20
        radius: 4
        x: root.leftPadding
        y: (parent.height - height) / 2

        Behavior on color {
            ColorAnimation {
                duration: Theme.mFast
                easing.type: Easing.OutCubic
            }
        }

        FluentIcon {
            anchors.centerIn: parent
            color: Theme.textOnAccent
            name: "Accept"
            size: 12
            visible: root.checked
        }
        FocusRing {
            active: root.visualFocus
            radiusOf: 4
        }
    }
}
