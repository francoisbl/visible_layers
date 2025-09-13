from functools import partial

from qgis.PyQt.QtWidgets import (
    QAction, QDockWidget, QListWidget, QListWidgetItem,
    QVBoxLayout, QWidget, QToolButton, QToolBar, QMenu
)
from qgis.PyQt.QtGui import QIcon, QPixmap
from qgis.PyQt.QtCore import Qt, QSize, QPoint
from qgis.core import QgsLayerTreeLayer, QgsWkbTypes, QgsProject, QgsVectorLayer
from qgis.utils import iface

import os


class VisibleLayers:
    def __init__(self, iface_):
        self.iface = iface_
        self.action = None
        self.dock = None
        self.list_widget = None
        self.button = None
        self.layer_states = {}         
        self._icon_connections = {} 
        self.dock_is_open = False

    def _icon_for_layernode(self, layer_id):
        lt_view = self.iface.layerTreeView()
        if not lt_view:
            return None
        model = lt_view.layerTreeModel()
        ltl = QgsProject.instance().layerTreeRoot().findLayer(layer_id)
        if not ltl:
            return None
        try:
            legend_nodes = model.layerLegendNodes(ltl)
            if legend_nodes:
                icon = legend_nodes[0].data(Qt.ItemDataRole.DecorationRole)
                if isinstance(icon, QPixmap):
                    icon = QIcon(icon)
                return icon if isinstance(icon, QIcon) else None
        except Exception:
            pass
        return None

    def initGui(self):
        self.action = QAction("Show Visible Layers Panel", self.iface.mainWindow())
        self.action.triggered.connect(self.toggle_dock)

        self.inject_button_in_layer_panel_toolbar()

        QgsProject.instance().layerTreeRoot().visibilityChanged.connect(
            self.sync_visibility_from_panel
        )
        QgsProject.instance().readProject.connect(self.auto_refresh_on_project_load)

    def unload(self):
        try:
            QgsProject.instance().layerTreeRoot().visibilityChanged.disconnect(
                self.sync_visibility_from_panel
            )
        except Exception:
            pass
        try:
            QgsProject.instance().readProject.disconnect(self.auto_refresh_on_project_load)
        except Exception:
            pass

        self._disconnect_icon_updates()

        if self.dock:
            self.iface.removeDockWidget(self.dock)
            self.dock = None
        if self.button:
            self.button.setParent(None)
            self.button = None

    def inject_button_in_layer_panel_toolbar(self):
        parent = self.iface.layerTreeView().parent()
        toolbar = parent.findChild(QToolBar)
        if toolbar:
            self.button = QToolButton()
            icon_path = os.path.join(os.path.dirname(__file__), "icons", "glasses_on.svg")
            icon = QIcon(icon_path)
            if icon.isNull():
                icon = QIcon.fromTheme("view-visible")
            self.button.setIcon(icon)
            self.button.setToolTip("Toggle Visible Layers")
            self.button.clicked.connect(self.toggle_dock)
            toolbar.addWidget(self.button)

    def toggle_dock(self):
        if not self.dock:
            self.create_dock()

        if self.dock_is_open:
            self.dock.hide()
            icon_path = os.path.join(os.path.dirname(__file__), "icons", "glasses_on.svg")
            if self.button:
                icon = QIcon(icon_path)
                if icon.isNull():
                    icon = QIcon.fromTheme("view-visible")
                self.button.setIcon(icon)
            self.dock_is_open = False
        else:
            self.update_visible_layers()
            self.dock.show()
            icon_path = os.path.join(os.path.dirname(__file__), "icons", "glasses_off.svg")
            if self.button:
                icon = QIcon(icon_path)
                if icon.isNull():
                    icon = QIcon.fromTheme("view-hidden")
                self.button.setIcon(icon)
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

        self.list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._show_context_menu)

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
            icon = QIcon(icon_path)
            if icon.isNull():
                icon = QIcon.fromTheme("view-visible")
            self.button.setIcon(icon)

    def update_visible_layers(self):
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        self.layer_states.clear()

        self._disconnect_icon_updates()

        root = QgsProject.instance().layerTreeRoot()

        for layer_node in root.findLayers():
            if not layer_node.isVisible():
                continue

            layer = layer_node.layer()
            if isinstance(layer, QgsVectorLayer):
                if not layer.isSpatial() or layer.geometryType() == QgsWkbTypes.NoGeometry:
                    continue

            item = QListWidgetItem(layer.name())
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            item.setData(Qt.ItemDataRole.UserRole, layer.id())

            icon = self._icon_for_layernode(layer.id())
            if icon:
                item.setIcon(icon)

            self.list_widget.addItem(item)
            self.layer_states[layer.id()] = item

            self._connect_icon_updates(layer)

        self.list_widget.blockSignals(False)

    def toggle_layer_visibility(self, item):
        layer_id = item.data(Qt.ItemDataRole.UserRole)
        node = QgsProject.instance().layerTreeRoot().findLayer(layer_id)
        if node:
            node.setItemVisibilityChecked(item.checkState() == Qt.Checked)

    def select_layer_in_panel(self, item):
        layer_id = item.data(Qt.ItemDataRole.UserRole)
        layer = QgsProject.instance().mapLayer(layer_id)
        if layer:
            self.iface.setActiveLayer(layer)

    def open_layer_properties(self, item):
        layer_id = item.data(Qt.ItemDataRole.UserRole)
        layer = QgsProject.instance().mapLayer(layer_id)
        if layer:
            self.iface.showLayerProperties(layer)

    def sync_visibility_from_panel(self, node):
        if not isinstance(node, QgsLayerTreeLayer):
            return
        layer_id = node.layerId()
        item = self.layer_states.get(layer_id)
        if item:
            item.setCheckState(Qt.Checked if node.isVisible() else Qt.Unchecked)

    def auto_refresh_on_project_load(self):
        if self.dock_is_open:
            self.update_visible_layers()

    def _show_context_menu(self, pos: QPoint):
        item = self.list_widget.itemAt(pos)
        if not item:
            return

        layer_id = item.data(Qt.ItemDataRole.UserRole)
        layer = QgsProject.instance().mapLayer(layer_id)
        if not layer:
            return

        self.iface.setActiveLayer(layer)
        lt_view = self.iface.layerTreeView()
        if not lt_view:
            return

        lt_view.setCurrentLayer(layer)

        provider = lt_view.menuProvider()
        if provider:
            menu = provider.createContextMenu()
            if menu:
                menu.exec_(self.list_widget.mapToGlobal(pos))
        else:
            menu = QMenu(self.list_widget)
            if self.iface.actionZoomToLayer():
                menu.addAction(self.iface.actionZoomToLayer())
            if self.iface.actionRenameLayer():
                menu.addAction(self.iface.actionRenameLayer())
            menu.exec_(self.list_widget.mapToGlobal(pos))

    def on_right_click(self, layer, pos: QPoint):
        if not layer:
            return
        self.iface.setActiveLayer(layer)
        lt_view = self.iface.layerTreeView()
        if not lt_view:
            return
        lt_view.setCurrentLayer(layer)
        provider = lt_view.menuProvider()
        if provider:
            menu = provider.createContextMenu()
            if menu:
                menu.exec_(self.list_widget.mapToGlobal(pos))
        else:
            menu = QMenu(self.list_widget)
            if self.iface.actionZoomToLayer():
                menu.addAction(self.iface.actionZoomToLayer())
            if self.iface.actionRenameLayer():
                menu.addAction(self.iface.actionRenameLayer())
            menu.exec_(self.list_widget.mapToGlobal(pos))

    def _connect_icon_updates(self, layer):
        lid = layer.id()
        if lid in self._icon_connections:
            return

        callbacks = []

        if hasattr(layer, "styleChanged"):
            cb = partial(self._refresh_item_icon, layer)
            layer.styleChanged.connect(cb)
            callbacks.append(("styleChanged", cb))

        if hasattr(layer, "rendererChanged"):
            cb = partial(self._refresh_item_icon, layer)
            layer.rendererChanged.connect(cb)
            callbacks.append(("rendererChanged", cb))

        if hasattr(layer, "repaintRequested"):
            cb = partial(self._refresh_item_icon, layer)
            layer.repaintRequested.connect(cb)
            callbacks.append(("repaintRequested", cb))

        self._icon_connections[lid] = (layer, callbacks)

    def _disconnect_icon_updates(self):
        for lid, (layer, callbacks) in list(self._icon_connections.items()):
            for sig_name, cb in callbacks:
                try:
                    getattr(layer, sig_name).disconnect(cb)
                except Exception:
                    pass
        self._icon_connections.clear()

    def _refresh_item_icon(self, layer):
        item = self.layer_states.get(layer.id())
        if not item:
            return

        icon = self._icon_for_layernode(layer.id())
        if icon:
            item.setIcon(icon)
