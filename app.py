import os, sys, time

sys.path.append(os.path.dirname(os.path.realpath(__file__)) + '/modules/')
sys.path.append(os.path.dirname(os.path.realpath(__file__)) + '/modules/qualisys_python_sdk')

from PySide2 import QtWidgets
from PySide2 import QtNetwork
from PySide2 import QtUiTools
from PySide2 import QtCore
from PySide2 import QtGui
from Qt import __binding__

import maya.api.OpenMaya as om
import maya.api.OpenMayaAnim as omanim
import maya.cmds as cmds
from maya.app.general.mayaMixin import MayaQWidgetDockableMixin

from qtm.packet import QRTComponentType
from qqtmrt import QQtmRt
from mayautil import MayaUtil
from markerstreamer import MarkerStreamer
from skeletonstreamer import SkeletonStreamer

MAYA = False

try:
    import maya.OpenMayaUI as OpenMayaUI

    if __binding__ in ('PySide2', 'PyQt5'):
        from shiboken2 import wrapInstance
    elif __binding__ in ('PySide', 'PyQt4'):
        from shiboken import wrapInstance
    else:
        _print_error('Cannot find Qt bindings.')

    MAYA = True

except:
    pass

def qtm_connect_gui():
    use_workspace_control = False

    if use_workspace_control:
        show_gui()
    else:
        d = QtmConnectWidget()
        d.show(dockable=True, height=800, width=480)

def start():
    parent = _get_maya_main_window()

    if not hasattr(parent, '_qtm') or not parent._qtm.connected:
        cmds.warning('Not connected to QTM.')
    else:
        parent._qtm.stream('3d')

def stop():
    parent = _get_maya_main_window()

    if not hasattr(parent, '_qtm') or not parent._qtm.connected:
        cmds.warning('Not connected to QTM.')
    else:
        parent._qtm.stop_stream()


def _get_maya_main_window():
    ptr = OpenMayaUI.MQtUtil.mainWindow()

    if ptr is None:
        raise RuntimeError('No Maya window found.')

    return wrapInstance(long(ptr), QtWidgets.QWidget)

def show_gui(restore=False):
    parent = _get_maya_main_window()

    ''' When the control is restoring, the workspace control has already been created and
    all that needs to be done is restoring its UI.
    '''
    if restore == True:
        # Grab the created workspace control with the following.
        restoredControl = omui.MQtUtil.getCurrentParent()

    if not hasattr(parent, 'customMixinWindow'):
        # Create a custom mixin widget for the first time.
        parent.customMixinWindow = QtmConnectWidget()
        parent.customMixinWindow.setObjectName('qtmConnectForMayaMixinWindow')

    if restore == True:
        # Add custom mixin widget to the workspace control.
        mixinPtr = omui.MQtUtil.findControl(parent.customMixinWindow.objectName())
        omui.MQtUtil.addWidgetToMayaLayout(long(mixinPtr), long(restoredControl))
    else:
        # Create a workspace control for the mixin widget by passing all the
        # needed parameters. See workspaceControl command documentation for all
        # available flags.
        parent.customMixinWindow.show(dockable=True, height=600, width=480, uiScript='show_gui(restore=True)')

    return parent.customMixinWindow

class QtmConnectWidget(MayaQWidgetDockableMixin, QtWidgets.QWidget):
    def __init__(self, parent=_get_maya_main_window() if MAYA else None):
        super(QtmConnectWidget, self).__init__(parent=parent)

        self.setWindowTitle('QTM Connect for Maya')
        self.setMinimumWidth(200)
        self.setWindowFlags(QtCore.Qt.Tool)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)

        self.widget = QtUiTools.QUiLoader().load(os.path.dirname(os.path.realpath(__file__)) + '/ui/qtm_connect.ui')
        layout = QtWidgets.QVBoxLayout(self)

        layout.addWidget(self.widget)

        self.marker_groups = None

        if hasattr(parent, '_qtm'):
            parent._qtm.stop_stream()
            parent._qtm.disconnect()

        self._qtm = QQtmRt()
        self._skeleton_streamer = SkeletonStreamer(self._qtm, self.widget.skeletonList)
        self._marker_streamer = MarkerStreamer(self._qtm, self.widget.markerList, self.widget.groupNameField)

        # Expose QQtmRt instance to following script runs.
        # The advantage of setting it on the parent is that we can reload the
        # module and still access it as opposed to a variable local to the module.
        parent._qtm = self._qtm

        self._qtm.connectedChanged.connect(self._connected_changed)
        self._qtm.streamingChanged.connect(self._streaming_changed)
        self._qtm.packetReceived.connect(self._packet_received)
        self._qtm.eventReceived.connect(self._event_received)

        self.widget.connectButton.clicked.connect(self.connect_qtm)
        self.widget.startButton.clicked.connect(self.stream)
        self.widget.stopButton.clicked.connect(self.stop_stream)
        self.widget.groupButton.clicked.connect(self._marker_streamer.group_markers)
        self.widget.markerList.clicked.connect(self.item_selected)
        self.widget.markerList.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.widget.markerList.setIconSize(QtCore.QSize(32, 16))
        self.widget.markerGroupButtonLayout.setAlignment(QtCore.Qt.AlignTop)
        self.widget.groupNameField.textChanged.connect(self.group_name_changed)
        self.widget.skeletonModeButton.toggled.connect(self.streaming_mode_changed)

        self.widget.streamingModeLayout.setContentsMargins(0, 11, 0, 0)
        self.widget.streamingModeLayout.setAlignment(QtCore.Qt.AlignLeft)
        self.widget.modeLabel.setFixedWidth(100)

        if cmds.optionVar(exists='qtmHost') == 1:
            hostname = 'localhost' if cmds.optionVar(q='qtmHost') == '' else cmds.optionVar(q='qtmHost')
        else:
            hostname = 'localhost'

        self.widget.hostField.textChanged.connect(self._host_changed)
        self.widget.hostField.setText(hostname)
        self._host = self.widget.hostField.text()
        self.is_streaming = False

        self.streaming_mode_changed()

    def streaming_mode_changed(self):
        self.widget.skeletonModeContainer.setVisible(self.widget.skeletonModeButton.isChecked())
        self.widget.markerModeContainer.setVisible(self.widget.markerModeButton.isChecked())

        if self.is_streaming:
            self._qtm.stop_stream()

        if self.widget.skeletonModeButton.isChecked():
            self._skeleton_streamer.create()

        if self.widget.markerModeButton.isChecked():
            self._marker_streamer.create()
        
    def _host_changed(self, text):
        self._host = text
        cmds.optionVar(sv=('qtmHost', text))

    def _packet_received(self, packet):
        if not isinstance(packet, basestring):
            if QRTComponentType.Component3d in packet.components:
                self._marker_streamer._packet_received(packet)

            if QRTComponentType.ComponentSkeleton in packet.components:
                self._skeleton_streamer._packet_received(packet)

    def _event_received(self, event):
        self._output('Event received: {}'.format(event))

    def _output(self, text):
        pass

    def _connected_changed(self, connected):
        self.is_connected = connected
        self.widget.connectButton.setText('Disconnect' if connected else 'Connect')
        self.widget.hostField.setEnabled(not connected)
        self.widget.startButton.setEnabled(connected)

        if connected:
            event = self._qtm.get_latest_event()
            self._output('Latest event: {}'.format(event))

    def group_name_changed(self):
        if self.widget.groupNameField.text() != '' and len(self.widget.markerList.selectedItems()) > 0:
            self.widget.groupButton.setEnabled(True)

    def item_selected(self, item):
        if self.widget.groupNameField.text() != '':
            self.widget.groupButton.setEnabled(True)
    
    def _streaming_changed(self, streaming):
        self.widget.startButton.setEnabled(not streaming)
        self.widget.stopButton.setEnabled(streaming)

    def stream(self):
        self._qtm.stream('skeleton' if self.widget.skeletonModeButton.isChecked() else '3d')
        self.is_streaming = True

    def stop_stream(self):
        self._qtm.stop_stream()
        self.is_streaming = False

    def get_settings_3d(self):
        self._output(str(self._qtm.get_settings('3d')))

    def connect_qtm(self):
        if self._qtm.connected:
            self._qtm.disconnect()
        else:
            self.widget.connectButton.setEnabled(False)
            self._qtm.connect_to_qtm(self._host, 3000)
            self.widget.connectButton.setEnabled(True)

            if not self._qtm.connected:
                cmds.warning('Could not connect to host.')

def main():
    if not MAYA:
        app = QtWidgets.QApplication(sys.argv)

    window = MainPlugin()
    window.show()

    if not MAYA:
        app.exec_()


if __name__ == '__main__':
    main()