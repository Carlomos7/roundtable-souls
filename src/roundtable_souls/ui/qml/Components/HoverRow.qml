pragma ComponentBehavior: Bound
import QtQuick
import Theme

// A list row (mod rows, character rows, tree rows). Rows are not cards (v2.5 D): no border, no radius, transparent
// at rest; hover = 4% fill, pressed = the ramp's pressed surface, selected = accent.soft. `divider` draws the
// hairline at the bottom, 56 px in from the left and 16 px short of the right edge. Inside a Card with padding 0,
// set `first` / `last` on the end rows so their corners follow the card's radius. Height 48 by default.
Rectangle {
    id: root

    default property alias content: inner.data
    property bool divider: false
    property bool first: false
    readonly property bool hovered: mouse.containsMouse
    property bool last: false
    property int padding: 12
    property bool pressable: true
    property bool selected: false

    signal clicked

    bottomLeftRadius: last ? Theme.radiusCard : 0
    bottomRightRadius: last ? Theme.radiusCard : 0
    color: mouse.pressed && pressable ? Theme.fillGhostPress : "transparent"
    implicitHeight: Theme.rowH
    radius: 0
    topLeftRadius: first ? Theme.radiusCard : 0
    topRightRadius: first ? Theme.radiusCard : 0

    Behavior on color {
        ColorAnimation {
            duration: Theme.mFast
            easing.type: Easing.OutCubic
        }
    }

    Smear {  // hover and selection = the glow smear (v2.8), not a filled row
        anchors.fill: parent
        bottomLeftRadius: root.bottomLeftRadius
        bottomRightRadius: root.bottomRightRadius
        strength: root.selected || mouse.containsMouse ? 1 : 0
        tint: root.selected ? Theme.smearSelected : Theme.smearHover
        topLeftRadius: root.topLeftRadius
        topRightRadius: root.topRightRadius
    }
    MouseArea {
        id: mouse

        anchors.fill: parent
        cursorShape: root.pressable ? Qt.PointingHandCursor : Qt.ArrowCursor
        hoverEnabled: true
        propagateComposedEvents: true

        onClicked: root.clicked()
    }
    Item {
        id: inner

        anchors.fill: parent
        anchors.leftMargin: root.padding
        anchors.rightMargin: root.padding
    }
    Hairline {
        endInset: Theme.dividerEndInset
        inset: Theme.dividerInset
        visible: root.divider
        y: Math.round(root.height) - 1
    }
}
