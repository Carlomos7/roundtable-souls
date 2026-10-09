pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Window
import Theme
import App
import Components

// A registered page in a top-level window of its own (S5: the Activity trial, opened from the Widgets launcher;
// the QML shell replaces this in S9 and hosts the same page unchanged). Around the page: a bar with the page's
// title and the status text, the page InfoBar, toasts bottom-right and the confirmation dialog, all driven by the
// page's Notifier (ui/notifications.py).
ApplicationWindow {
    id: win

    required property var adapter
    required property var notifier
    required property url pageUrl
    property string themeMode: "dark"   // "dark" | "tarnished" | "light" | "system", from the launcher's setting
    property Item toastItem: null
    property int confirmToken: 0
    property bool confirmed: false

    color: Theme.surfacePage
    height: 760
    minimumHeight: 480
    minimumWidth: 740
    title: win.adapter ? win.adapter.title + "  ·  Roundtable Souls" : "Roundtable Souls"
    width: 1100

    Component.onCompleted: {
        AppState.softwareRender = GraphicsInfo.api === GraphicsInfo.Software;
        AppState.setThemeMode(win.themeMode);
    }
    onThemeModeChanged: AppState.setThemeMode(win.themeMode)

    Rectangle {  // the bar: title left, the status text right
        id: bar

        color: Theme.surfaceBar
        height: Theme.barRowH
        width: parent.width

        Txt {
            anchors.left: parent.left
            anchors.leftMargin: Theme.sp16
            anchors.verticalCenter: parent.verticalCenter
            kind: "strong"
            text: win.adapter ? win.adapter.title : ""
        }
        Txt {
            anchors.right: parent.right
            anchors.rightMargin: Theme.sp16
            anchors.verticalCenter: parent.verticalCenter
            color: Theme.textSecondary
            kind: "caption"
            text: win.notifier.statusText
        }
    }
    InfoBar {
        id: infoBar

        anchors.left: parent.left
        anchors.leftMargin: Theme.sp16
        anchors.right: parent.right
        anchors.rightMargin: Theme.sp16
        anchors.top: bar.bottom
        anchors.topMargin: visible ? Theme.sp8 : 0
        open: win.notifier.infoText !== ""
        severity: win.notifier.infoSeverity
        text: win.notifier.infoText
        visible: open

        onClosed: win.notifier.clear_info()
    }
    Loader {
        id: page

        anchors.bottom: parent.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: infoBar.visible ? infoBar.bottom : bar.bottom

        Component.onCompleted: page.setSource(win.pageUrl, {
            "adapter": win.adapter
        })
    }
    Item {  // toasts float above the page
        id: overlay

        anchors.fill: parent
        z: 10

        Component.onCompleted: AppState.overlayLayer = overlay
    }
    Component {
        id: toastComponent

        Toast {
            anchors.bottom: parent ? parent.bottom : undefined
            anchors.bottomMargin: Theme.padDialog
            anchors.right: parent ? parent.right : undefined
            anchors.rightMargin: Theme.padDialog

            onDone: destroy()
        }
    }
    Connections {
        function onToastRequested(text, isError) {
            if (win.toastItem)
                win.toastItem.dismiss();
            win.toastItem = toastComponent.createObject(overlay, {
                "text": text,
                "isError": isError
            });
        }
        function onConfirmRequested(token, title, changes, safety, applyText, destructive) {
            win.confirmToken = token;
            win.confirmed = false;
            confirm.title = title;
            confirm.message = changes.map(function (c) {
                return "• " + c;
            }).concat(safety ? ["", safety] : []).join("\n");
            confirm.primaryText = applyText;
            confirm.destructive = destructive;
            confirm.open();
        }

        target: win.notifier
    }
    ConfirmDialog {
        id: confirm

        onClosed: win.notifier.answer(win.confirmToken, win.confirmed)
        onConfirm: function () {
            win.confirmed = true;
        }
    }
}
