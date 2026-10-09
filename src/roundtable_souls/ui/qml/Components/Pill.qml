pragma ComponentBehavior: Bound
import QtQuick
import Theme

// A tag (v2.5 D): no fill, a 12% hairline border, fully rounded (v2.15), 11 px text at 90%, 2x6 padding, 20 px tall. Coloured
// levels (success | warning | danger | accent | info) tint border and text only; "muted" is the neutral tag.
// `filled: true` is for the ONE filled pill (the health pill): status.bg fill, pill radius, no border.
Rectangle {
    id: root

    readonly property color bgc: level === "success" ? Theme.statusSuccessBg : level === "warning" ? Theme.statusWarningBg : level === "danger" ? Theme.statusDangerBg : level === "accent" || level === "info" ? Theme.accentSoft : Theme.fillGhost
    property bool clickable: false
    readonly property color fg: level === "success" ? Theme.statusSuccess : level === "warning" ? Theme.statusWarning : level === "danger" ? Theme.statusDanger : level === "accent" ? Theme.accent : level === "info" ? Theme.statusInfo : Theme.textPrimary
    property bool filled: false
    property string icon_: ""
    property string level: "muted"
    property string text

    signal clicked

    border.color: filled ? "transparent" : level === "muted" ? Theme.borderTag : Qt.rgba(fg.r, fg.g, fg.b, 0.5)
    border.width: filled ? 0 : 1
    color: filled ? bgc : (mouse.containsMouse && clickable ? Theme.fillHover : "transparent")
    implicitHeight: 20
    implicitWidth: row.implicitWidth + 12
    radius: height / 2  // v2.15: tags stay rounded (owner)

    Behavior on border.color {
        ColorAnimation {
            duration: Theme.mFast
            easing.type: Easing.OutCubic
        }
    }
    Behavior on color {
        ColorAnimation {
            duration: Theme.mFast
            easing.type: Easing.OutCubic
        }
    }

    Row {
        id: row

        anchors.centerIn: parent
        opacity: 0.9
        spacing: Theme.sp4

        FluentIcon {
            anchors.verticalCenter: parent.verticalCenter
            color: root.fg
            name: root.icon_
            size: 11
            visible: root.icon_ !== ""
        }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            color: root.fg
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontTag
            font.weight: Font.Medium
            text: root.text

            Behavior on color {
                ColorAnimation {
                    duration: Theme.mFast
                    easing.type: Easing.OutCubic
                }
            }
        }
    }
    MouseArea {
        id: mouse

        anchors.fill: parent
        cursorShape: Qt.PointingHandCursor
        enabled: root.clickable
        hoverEnabled: true

        onClicked: root.clicked()
    }
}
