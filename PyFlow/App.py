import os
import sys
import subprocess
import json
from time import clock
import pkgutil

from Qt import QtGui
from Qt import QtCore
from Qt.QtWidgets import QMainWindow
from Qt.QtWidgets import QApplication
from Qt.QtWidgets import QStyleFactory
from Qt.QtWidgets import QSizePolicy
from Qt.QtWidgets import QTextEdit
from Qt.QtWidgets import QMessageBox
from Qt.QtWidgets import QAction
from Qt.QtWidgets import QInputDialog
from Qt.QtWidgets import QHBoxLayout
from Qt.QtWidgets import QUndoView
from Qt.QtWidgets import QToolButton
from Qt.QtWidgets import QPushButton
from Qt.QtWidgets import QSpacerItem
from Qt.QtWidgets import QFileDialog

from PyFlow import Packages
from PyFlow.UI.Canvas.Canvas import Canvas
from PyFlow.Core.Common import Direction
from PyFlow.UI.Canvas.UICommon import clearLayout
from PyFlow.Core.GraphBase import GraphBase
from PyFlow.Core.GraphManager import GraphManager
from PyFlow.UI.Views.NodeBox import NodesBox
from PyFlow.UI.Canvas.UINodeBase import getUINodeInstance
from PyFlow.UI.Widgets import GraphEditor_ui
from PyFlow.UI.Views.VariablesWidget import VariablesWidget
from PyFlow.UI.Utils.StyleSheetEditor import StyleSheetEditor
from PyFlow import INITIALIZE


FILE_DIR = os.path.abspath(os.path.dirname(__file__))
SETTINGS_PATH = os.path.join(FILE_DIR, "appConfig.ini")
STYLE_PATH = os.path.join(FILE_DIR, "style.css")
EDITOR_TARGET_FPS = 120


def open_file(filename):
    if sys.platform == "win32":
        os.startfile(filename)
    else:
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        subprocess.call([opener, filename])


class PluginType:
    pNode = 0
    pCommand = 1
    pFunctionLibrary = 2
    pPin = 3


def _implementPlugin(name, pluginType):
    pass


## App itself
class PyFlow(QMainWindow, GraphEditor_ui.Ui_MainWindow):
    newFileExecuted = QtCore.Signal(bool)

    def __init__(self, parent=None):
        super(PyFlow, self).__init__(parent=parent)
        self.setupUi(self)
        self.listViewUndoStack = QUndoView(self.dockWidgetContents_3)
        self.listViewUndoStack.setObjectName("listViewUndoStack")
        self.gridLayout_6.addWidget(self.listViewUndoStack, 0, 0, 1, 1)

        self.styleSheetEditor = StyleSheetEditor()
        self.graphManager = GraphManager()
        self.canvasWidget = Canvas(self.graphManager, self)
        self.canvasWidget.graphManager.graphChanged.connect(self.updateGraphTreeLocation)
        self.newFileExecuted.connect(self.canvasWidget.shoutDown)
        self.updateGraphTreeLocation()
        self.SceneLayout.addWidget(self.canvasWidget)

        self.actionVariables.triggered.connect(self.toggleVariables)
        self.actionPlot_graph.triggered.connect(self.canvasWidget.plot)
        self.actionDelete.triggered.connect(self.on_delete)
        self.actionPropertyView.triggered.connect(self.togglePropertyView)
        self.actionScreenshot.triggered.connect(self.canvasWidget.screenShot)
        self.actionShortcuts.triggered.connect(self.shortcuts_info)

        self.actionSave.triggered.connect(self.save)
        self.actionLoad.triggered.connect(self.load)
        self.actionSave_as.triggered.connect(lambda: self.save(True))
        self.actionNew.triggered.connect(self.newFile)

        self.actionAlignLeft.triggered.connect(lambda: self.canvasWidget.alignSelectedNodes(Direction.Left))
        self.actionAlignUp.triggered.connect(lambda: self.canvasWidget.alignSelectedNodes(Direction.Up))
        self.actionAlignBottom.triggered.connect(lambda: self.canvasWidget.alignSelectedNodes(Direction.Down))
        self.actionAlignRight.triggered.connect(lambda: self.canvasWidget.alignSelectedNodes(Direction.Right))
        self.actionNew_Node.triggered.connect(lambda: self.newPlugin(PluginType.pNode))
        self.actionNew_Command.triggered.connect(lambda: self.newPlugin(PluginType.pCommand))
        self.actionFunction_Library.triggered.connect(lambda: self.newPlugin(PluginType.pFunctionLibrary))
        self.actionNew_pin.triggered.connect(lambda: self.newPlugin(PluginType.pPin))
        self.actionHistory.triggered.connect(self.toggleHistory)
        self.dockWidgetUndoStack.setVisible(False)

        rxLettersAndNumbers = QtCore.QRegExp('^[a-zA-Z0-9]*$')
        nameValidator = QtGui.QRegExpValidator(rxLettersAndNumbers, self.leCompoundName)
        self.leCompoundName.setValidator(nameValidator)
        self.leCompoundName.returnPressed.connect(self.onActiveCompoundNameAccepted)

        rxLetters = QtCore.QRegExp('^[a-zA-Z]*$')
        categoryValidator = QtGui.QRegExpValidator(rxLetters, self.leCompoundCategory)
        self.leCompoundCategory.setValidator(categoryValidator)
        self.leCompoundCategory.returnPressed.connect(self.onActiveCompoundCategoryAccepted)

        self.setMouseTracking(True)

        self.variablesWidget = VariablesWidget(self.canvasWidget)
        self.leftDockGridLayout.addWidget(self.variablesWidget)

        self._lastClock = 0.0
        self.fps = EDITOR_TARGET_FPS
        self.tick_timer = QtCore.QTimer()
        self._current_file_name = 'Untitled'

    def setCompoundPropertiesWidgetVisible(self, bVisible):
        if bVisible:
            self.CompoundPropertiesWidget.show()
            self.leCompoundName.setText(self.graphManager.activeGraph().name)
            self.leCompoundCategory.setText(self.graphManager.activeGraph().category)
        else:
            self.CompoundPropertiesWidget.hide()

    def keyPressEvent(self, event):
        modifiers = event.modifiers()
        if all([event.key() == QtCore.Qt.Key_N, modifiers == QtCore.Qt.ControlModifier]):
            self.newFile()
        if all([event.key() == QtCore.Qt.Key_S, modifiers == QtCore.Qt.ControlModifier]):
            self.save()
        if all([event.key() == QtCore.Qt.Key_O, modifiers == QtCore.Qt.ControlModifier]):
            self.load()
        if all([event.key() == QtCore.Qt.Key_S, modifiers == QtCore.Qt.ControlModifier | QtCore.Qt.ShiftModifier]):
            self.save_as()

    def loadFromData(self, data, fpath=""):
        self.newFile(keepRoot=False)
        # load raw data
        self.graphManager.deserialize(data)
        # create ui nodes
        for graph in self.graphManager.getAllGraphs():
            self.canvasWidget.createWrappersForGraph(graph)
        self.graphManager.selectRootGraph()
        self.variablesWidget.actualize()

    def load(self):
        name_filter = "Graph files (*.json)"
        savepath = QFileDialog.getOpenFileName(filter=name_filter)
        if type(savepath) in [tuple, list]:
            fpath = savepath[0]
        else:
            fpath = savepath
        if not fpath == '':
            with open(fpath, 'r') as f:
                data = json.load(f)
                self.loadFromData(data, fpath)

    def save(self, save_as=False):
        if save_as:
            name_filter = "Graph files (*.json)"
            savepath = QFileDialog.getSaveFileName(filter=name_filter)
            if type(savepath) in [tuple, list]:
                pth = savepath[0]
            else:
                pth = savepath
            if not pth == '':
                self._current_file_name = pth
            else:
                self._current_file_name = "Untitled"
        else:
            if not os.path.isfile(self._current_file_name):
                name_filter = "Graph files (*.json)"
                savepath = QFileDialog.getSaveFileName(filter=name_filter)
                if type(savepath) in [tuple, list]:
                    pth = savepath[0]
                else:
                    pth = savepath
                if not pth == '':
                    self._current_file_name = pth
                else:
                    self._current_file_name = "Untitled"

        if self._current_file_name in ["", "Untitled"]:
            return

        if not self._current_file_name == '':
            with open(self._current_file_name, 'w') as f:
                saveData = self.graphManager.serialize()
                json.dump(saveData, f, indent=4)

            print(str("// saved: '{0}'".format(self._current_file_name)))

    def clearPropertiesView(self):
        clearLayout(self.propertiesLayout)

    def newFile(self, keepRoot=True):
        self.tick_timer.stop()
        self.tick_timer.timeout.disconnect()

        # broadcast
        self.graphManager.clear(keepRoot=keepRoot)
        self.newFileExecuted.emit(keepRoot)
        self._current_file_name = 'Untitled'
        self.clearPropertiesView()
        self.variablesWidget.actualize()

        self.startMainLoop()

    def updateGraphTreeLocation(self, *args, **kwargs):
        location = self.canvasWidget.location()
        clearLayout(self.layoutGraphPath)
        spacerItem = QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.layoutGraphPath.addItem(spacerItem)
        for folderName in location:
            index = self.layoutGraphPath.count() - 1
            btn = QPushButton(folderName)

            def onClicked(checked, name=None):
                self.canvasWidget.stepToCompound(name)

            btn.clicked.connect(lambda chk=False, name=folderName: onClicked(chk, name))
            self.layoutGraphPath.insertWidget(index, btn)

        self.setCompoundPropertiesWidgetVisible(self.graphManager.activeGraph().depth() > 1)

    def onActiveCompoundNameAccepted(self):
        newName = self.graphManager.getUniqName(self.leCompoundName.text())
        self.graphManager.activeGraph().name = newName
        self.leCompoundName.blockSignals(True)
        self.leCompoundName.setText(newName)
        self.leCompoundName.blockSignals(False)
        self.updateGraphTreeLocation()

    def onActiveCompoundCategoryAccepted(self):
        newCategoryName = self.leCompoundCategory.text()
        self.graphManager.activeGraph().category = newCategoryName

    def startMainLoop(self):
        self.tick_timer.timeout.connect(self.mainLoop)
        self.tick_timer.start(1000 / EDITOR_TARGET_FPS)

    def stopMainLoop(self):
        self.tick_timer.stop()
        self.tick_timer.timeout.disconnect()

    def mainLoop(self):
        deltaTime = clock() - self._lastClock
        ds = (deltaTime * 1000.0)
        if ds > 0:
            self.fps = int(1000.0 / ds)

        # Tick all graphs
        # each graph will tick owning raw nodes
        # each raw node will tick it's ui wrapper if it exists
        self.graphManager.Tick(deltaTime)

        # Tick canvas. Update ui only stuff such animation etc.
        self.canvasWidget.Tick(deltaTime)

        self._lastClock = clock()

    def createPopupMenu(self):
        pass

    def toggleHistory(self):
        self.dockWidgetUndoStack.setVisible(
            not self.dockWidgetUndoStack.isVisible())

    def newPlugin(self, pluginType):
        name, result = QInputDialog.getText(
            self, 'Plugin name', 'Enter plugin name')
        if result:
            _implementPlugin(name, pluginType)

    def closeEvent(self, event):
        self.tick_timer.stop()
        self.tick_timer.timeout.disconnect()
        self.canvasWidget.shoutDown()
        # save editor config
        settings = QtCore.QSettings(
            SETTINGS_PATH, QtCore.QSettings.IniFormat, self)
        settings.beginGroup('Editor')
        settings.setValue("geometry", self.saveGeometry())
        settings.setValue("windowState", self.saveState())
        settings.endGroup()
        QMainWindow.closeEvent(self, event)

    def applySettings(self, settings):
        self.restoreGeometry(settings.value('Editor/geometry'))
        self.restoreState(settings.value('Editor/windowState'))

    def editTheme(self):
        self.styleSheetEditor.show()

    def updateStyle(self):
        pass
        # if self.styleSheetEditor:
        #    self.setStyleSheet(self.styleSheetEditor.getStyleSheet())

    def togglePropertyView(self):
        if self.dockWidgetNodeView.isVisible():
            self.dockWidgetNodeView.setVisible(False)
        else:
            self.dockWidgetNodeView.setVisible(True)

    def toggleVariables(self):
        if self.dockWidgetVariables.isVisible():
            self.dockWidgetVariables.hide()
        else:
            self.dockWidgetVariables.show()

    def shortcuts_info(self):

        data = "Tab - togle node box\n"
        data += "Ctrl+N - new file\n"
        data += "Ctrl+S - save\n"
        data += "Ctrl+Shift+S - save as\n"
        data += "Ctrl+O - open file\n"
        data += "F - frame selected\n"
        data += "H - frame all\n"
        data += "C - comment selected nodes\n"
        data += "Delete - kill selected nodes\n"
        data += "Ctrl+C - Copy\n"
        data += "Ctrl+V - Paste\n"
        data += "Alt+Drag - Duplicate\n"
        data += "Ctrl+Z - Undo\n"
        data += "Ctrl+Y - Redo\n"
        data += "Alt+Click - Disconnect Pin\n"
        data += "Ctrl+Shift+ArrowLeft - Align left\n"
        data += "Ctrl+Shift+ArrowUp - Align Up\n"
        data += "Ctrl+Shift+ArrowRight - Align right\n"
        data += "Ctrl+Shift+ArrowBottom - Align Bottom\n"

        QMessageBox.information(self, "Shortcuts", data)

    def on_delete(self):
        self.canvasWidget.killSelectedNodes()

    @staticmethod
    def instance(parent=None):
        settings = QtCore.QSettings(SETTINGS_PATH, QtCore.QSettings.IniFormat)
        instance = PyFlow(parent)
        instance.applySettings(settings)
        instance.startMainLoop()
        INITIALIZE()

        # fetch input widgets
        # do it separately from raw classes, since this is ui related code
        for importer, modname, ispkg in pkgutil.iter_modules(Packages.__path__):
            if ispkg:
                mod = importer.find_module(modname).load_module(modname)
                FactoriesPath = mod.__path__[0]
                FactoriesImporter = pkgutil.get_importer(FactoriesPath)
                FactoriesModuleLoader = FactoriesImporter.find_module(
                    'Factories')
                if FactoriesModuleLoader is not None:
                    FactoriesModule = FactoriesModuleLoader.load_module(
                        'Factories')
        return instance