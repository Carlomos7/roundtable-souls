pragma ComponentBehavior: Bound
import QtQuick
import Theme

// A card (v2.5 D): hairline + a soft resting shadow (y1 blur3 25%), radius 8, no opaque 1 px border. Things that
// stay. A group of rows (Packages, Natives, characters, settings) is ONE card: set `padding: 0`, put HoverRow /
// FormRow inside with `divider: index < count - 1`, and `first` / `last` on the end rows so their corners follow
// the card. The hairline is painted above the content so a hovered row never covers it. The page grain shows
// through the translucent fill; cards add none of their own (v2.10).
Item {
    id: root

    property alias color: body.color
    default property alias content: inner.data
    property bool hairline: true
    property int padding: Theme.padCard   // v2.16: one card inset everywhere
    property alias radius: body.radius

    implicitHeight: inner.childrenRect.height + padding * 2
    implicitWidth: 200

    SoftShadow {
        elevation: "rest"
        radius: body.radius
        target: body
    }
    Rectangle {
        id: body

        anchors.fill: parent
        color: Theme.cardFill
        radius: Theme.radiusCard

        Behavior on color {
            ColorAnimation {
                duration: Theme.mToggle
                easing.type: Easing.OutCubic
            }
        }

        // no Grain here (v2.10): the translucent card fill shows the page grain; a second layer doubled it

        Item {
            id: inner

            anchors.fill: parent
            anchors.margins: root.padding
        }
        Rectangle {  // the hairline, above the content
            anchors.fill: parent
            border.color: Theme.borderHairline
            border.width: 1
            color: "transparent"
            radius: body.radius
            visible: root.hairline
            z: 5

            Behavior on border.color {
                ColorAnimation {
                    duration: Theme.mToggle
                    easing.type: Easing.OutCubic
                }
            }
        }
    }
}
