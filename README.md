<h1><img src="icon.png" alt="Logo" width="24" style="vertical-align:middle;"/> Visible Layers</h1>

Visible Layers is a lightweight plugin for QGIS that displays only the layers currently visible (toggled) in your project, inside a dedicated dock panel.

It enhances readability and efficiency when working with complex projects by allowing users to focus solely on the layers that matter.
## Features

- Show only visible layers (i.e., checked in the Layers Panel)
- Toggle the panel using a toolbar button directly inside the Layers Panel
- Auto-refresh when opening a new QGIS project
- Refresh manually if needed using a "Refresh" button
- Click a layer in the dock to select it in the Layers Panel
- Double-click a layer to open its Layer Properties dialog
- Synchronize visibility: checking/unchecking a layer in the dock updates the main panel
- Preserves layer order and integrates without affecting your project structure
- Uses SVG icons, native QGIS styling, and no external dependencies

## Typical use cases

- Quickly scan only the layers that are currently shown on the map
- Declutter your interface when navigating complex projects with many utility/background layers
- Share a screenshot or perform visual analysis with only relevant layers visible
- Stay focused when toggling themes, temporal layers, or mapsheets

## How to use the plugin

<img src="docs/visible_layers.png" alt="Screenshot" width="720"/>
Only the checked layers are listed in the "Visible Layers" panel for quick access and editing.

## Installation

**From QGIS (recommended)**
1. In QGIS: **Plugins → Manage and Install Plugins…**
2. Search for **“Visible Layers”** (official QGIS Plugins repo)
3. Click **Install** and enable the plugin

**From ZIP**
1. Download the latest `visible_layers.zip` from Releases
2. In QGIS: **Plugins → Manage and Install… → Install from ZIP** → select the file
3. Restart QGIS if needed

## Compatibility

QGIS **3.x and 4.x** (Qt6-ready).

## About

This tiny plugin was developed to support day-to-day GIS workflows with clarity and simplicity. Since I now use it in all my own projects, I thought it might be worth sharing.

## Feedback & contributions

Feel free to open issues or suggest improvements.

You can also leave a suggestion on [this Reddit thread](https://www.reddit.com/r/QGIS/comments/1l1ehbi/i_made_a_tiny_qgis_plugin_to_filter_visible_layers/).
