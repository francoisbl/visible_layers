from qgis.PyQt.QtWidgets import (
    QAction, QDockWidget, QListWidget, QListWidgetItem,
    QVBoxLayout, QWidget, QPushButton, QToolButton, QToolBar
)
from qgis.PyQt.QtGui import QIcon
from PyQt5.QtCore import QSize 
from qgis.PyQt.QtCore import Qt
from qgis.core import QgsProject
from qgis.core import QgsLayerTreeLayer
from qgis.core import QgsWkbTypes
from qgis.core import QgsVectorLayer
from qgis.utils import iface
import os

class VisibleLayers:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.dock = None
        self.list_widget = None
        self.button = None
        self.layer_states = {}
        self.dock_is_open = False

    def initGui(self):
        self.action = QAction("Show Visible Layers Panel", self.iface.mainWindow())
        self.action.triggered.connect(self.toggle_dock)
        self.iface.addToolBarIcon(self.action)
        self.inject_button_in_layer_panel_toolbar()
        QgsProject.instance().layerTreeRoot().visibilityChanged.connect(self.sync_visibility_from_panel)
        QgsProject.instance().readProject.connect(self.auto_refresh_on_project_load)

    def inject_button_in_layer_panel_toolbar(self):
        parent = iface.layerTreeView().parent()
        toolbar = parent.findChild(QToolBar)
        if toolbar:
            self.button = QToolButton()
            icon_path = os.path.join(os.path.dirname(__file__), "icons", "glasses_on.svg")
            self.button.setIcon(QIcon(icon_path))
            self.button.setToolTip("Toggle Visible Layers")
            self.button.clicked.connect(self.toggle_dock)
            toolbar.addWidget(self.button)

    def toggle_dock(self):
        if not self.dock:
            self.create_dock()

        if self.dock_is_open:
            self.dock.hide()
            icon_path = os.path.join(os.path.dirname(__file__), "icons", "glasses_on.svg")
            self.button.setIcon(QIcon(icon_path))
            self.dock_is_open = False
        else:
            self.update_visible_layers()
            self.dock.show()
            icon_path = os.path.join(os.path.dirname(__file__), "icons", "glasses_off.svg")
            self.button.setIcon(QIcon(icon_path))
            self.dock_is_open = True

    def create_dock(self):
        self.dock = QDockWidget("Visible Layers", self.iface.mainWindow())
        main_widget = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        toolbar = QToolBar()
        toolbar.setIconSize(QSize(16, 16))
        toolbar.setStyleSheet("QToolBar { border: none; }")
        refresh_action = QAction(
            QIcon(":/images/themes/default/mActionRefresh.svg"),
            "Refresh visible layers",
            self.iface.mainWindow()
        )
        refresh_action.triggered.connect(self.update_visible_layers)
        toolbar.addAction(refresh_action)

        self.list_widget = QListWidget()
        self.list_widget.itemClicked.connect(self.select_layer_in_panel)
        self.list_widget.itemChanged.connect(self.toggle_layer_visibility)
        self.list_widget.itemDoubleClicked.connect(self.open_layer_properties)

        layout.addWidget(toolbar)
        layout.addWidget(self.list_widget)
        main_widget.setLayout(layout)

        self.dock.setWidget(main_widget)
        self.iface.addDockWidget(Qt.LeftDockWidgetArea, self.dock)
        self.dock.visibilityChanged.connect(self._update_dock_state)

    def _update_dock_state(self, visible):
        self.dock_is_open = visible
        if not visible and self.button:
            icon_path = os.path.join(os.path.dirname(__file__), "icons", "glasses_on.svg")
            self.button.setIcon(QIcon(icon_path))

    def update_visible_layers(self):
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        self.layer_states.clear()
        for layer_node in QgsProject.instance().layerTreeRoot().findLayers():
            if not layer_node.isVisible():
                continue
            layer = layer_node.layer()
            if isinstance(layer, QgsVectorLayer):
                if not layer.isSpatial() or layer.geometryType() == QgsWkbTypes.NoGeometry:
                    continue
            item = QListWidgetItem(layer.name())
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            item.setData(Qt.UserRole, layer.id())
            self.list_widget.addItem(item)
            self.layer_states[layer.id()] = item
        self.list_widget.blockSignals(False)

    def toggle_layer_visibility(self, item):
        layer_id = item.data(Qt.UserRole)
        node = QgsProject.instance().layerTreeRoot().findLayer(layer_id)
        if node:
            node.setItemVisibilityChecked(item.checkState() == Qt.Checked)

    def select_layer_in_panel(self, item):
        layer_id = item.data(Qt.UserRole)
        layer = QgsProject.instance().mapLayer(layer_id)
        if layer:
            iface.setActiveLayer(layer)

    def open_layer_properties(self, item):
        layer_id = item.data(Qt.UserRole)
        layer = QgsProject.instance().mapLayer(layer_id)
        if layer:
            iface.showLayerProperties(layer)

    def sync_visibility_from_panel(self, node):
        if not isinstance(node, QgsLayerTreeLayer):
            return  # Skip group nodes or others
        layer_id = node.layerId()
        item = self.layer_states.get(layer_id)
        if item:
            item.setCheckState(Qt.Checked if node.isVisible() else Qt.Unchecked)

    def auto_refresh_on_project_load(self):
        if self.dock_is_open:
            self.update_visible_layers()

    def unload(self):
        self.iface.removeToolBarIcon(self.action)
        if self.dock:
            self.iface.removeDockWidget(self.dock)
        if self.button:
            self.button.setParent(None)
            self.button = None
        QgsProject.instance().layerTreeRoot().visibilityChanged.disconnect(self.sync_visibility_from_panel)
        QgsProject.instance().readProject.disconnect(self.auto_refresh_on_project_load)
