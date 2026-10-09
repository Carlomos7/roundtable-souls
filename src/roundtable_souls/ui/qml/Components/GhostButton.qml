pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import Theme

// The secondary button (v2.9): transparent with a 1 px edge outline and normal text. Hover: the glow smear behind it,
// the outline turns accent (55%) and the icon turns accent. `flat` drops the outline (the "plain" style). Disabled:
// tertiary text, no hover. Keyboard focus shows the ring (Tab focus only).
Button {
    id: root

    property color fg: Theme.textPrimary
    property color hoverColor: Theme.smearHover   // kept for callers that set it; the smear uses it
    property string icon_: ""                     // a Fluent icon name

    focusPolicy: Qt.TabFocus
    font.family: Theme.fontFamily
    font.pixelSize: Theme.fontBody
    font.weight: Font.Medium
    hoverEnabled: true
    implicitHeight: Theme.controlH
    implicitWidth: icon_ !== "" && text === "" ? Theme.controlH : Math.max(Theme.buttonMinW, row.implicitWidth + Theme.sp16 * 2)  // icon-only = square
    scale: down ? 0.98 : 1

    background: Rectangle {
        border.color: root.flat ? "transparent" : root.hovered && root.enabled ? Theme.goldLine : Theme.borderEdge
        border.width: 1
        color: root.down ? Theme.fillGhostPress : "transparent"
        radius: Theme.radiusControl

        Behavior on border.color {
            ColorAnimation {
                duration: Theme.mFast
                easing.type: Easing.OutCubic
            }
        }

        Smear {
            anchors.fill: parent
            anchors.margins: 1
            peak: 0.5
            radius: Theme.radiusControl
            strength: root.hovered && root.enabled ? 1 : 0
            tint: root.hoverColor
        }
        FocusRing {
            active: root.visualFocus
            radiusOf: Theme.radiusControl
        }
    }
    contentItem: Row {
        id: row

        anchors.centerIn: parent
        spacing: Theme.sp8

        FluentIcon {
            anchors.verticalCenter: parent.verticalCenter
            color: !root.enabled ? Theme.textDisabled : root.hovered ? Theme.goldText : Theme.textSecondary
            name: root.icon_
            size: 16
            visible: root.icon_ !== ""
        }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            color: root.enabled ? (root.flat && !root.hovered ? Theme.textSecondary : root.fg) : Theme.textDisabled
            font: root.font
            text: root.text

            Behavior on color {
                ColorAnimation {
                    duration: Theme.mFast
                    easing.type: Easing.OutCubic
                }
            }
        }
    }
    Behavior on scale {
        NumberAnimation {
            duration: Theme.mPress
            easing.type: Easing.OutCubic
        }
    }
}
