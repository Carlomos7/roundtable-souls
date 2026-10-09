pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.impl
import Theme

// One Fluent icon, tinted. `name` is a FluentIcon file name (BookShelf, Save, Setting, ...). IconImage recolours
// on the CPU (what Qt's own controls use for icon.color), so it needs no shader and works everywhere.
// Default colour = text at 80% (v2.5 D); 16 in rows, 20 in buttons and the rail.
Item {
    id: root

    property color color: Theme.textIcon
    property string name
    property int size: 16

    implicitHeight: size
    implicitWidth: size

    IconImage {
        anchors.fill: parent
        color: root.color
        fillMode: Image.PreserveAspectFit
        smooth: true
        source: root.name ? Theme.icon(root.name) : ""
        sourceSize: Qt.size(root.size, root.size)

        Behavior on color {
            ColorAnimation {
                duration: Theme.mFast
                easing.type: Easing.OutCubic
            }
        }
    }
}
