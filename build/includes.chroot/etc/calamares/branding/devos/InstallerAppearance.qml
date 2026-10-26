pragma Singleton
import QtQuick 2.15

QtObject {
    // Shared for this installer session, including pages loaded later.
    property bool motionEnabled: true
}
