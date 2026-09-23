# Workspaces
Arlo features an embedded tiling workspace system for displaying interactive content alongside the assistant. Workspaces live inside the main application window, without opening additional windows or creating separate Arlo instances.

## Keyboard shortcuts
Workspaces are managed entirely through keyboard shortcuts, keeping the interface clean and free of unnecessary toolbars.

| Shortcut         | Action                                |
|------------------|---------------------------------------|
| `Ctrl + N`       | Open a new workspace panel.           |
| `Ctrl + W`       | Close the active panel.               |
| `Ctrl + Alt + ←` | Focus the nearest panel to the left.  |
| `Ctrl + Alt + →` | Focus the nearest panel to the right. |
| `Ctrl + Alt + ↑` | Focus the nearest panel above.        |
| `Ctrl + Alt + ↓` | Focus the nearest panel below.        |

The active panel is highlighted, and closing it automatically selects another available panel.

## How tiling works
Arlo uses a binary tiling layout built with Qt splitters. Each new panel divides an existing workspace into two regions, alternating between horizontal and vertical splits.
Panels automatically share the available space. You can drag the separators between them to resize individual regions without affecting their content.
Opening and closing panels triggers smooth size transitions. When a panel closes, its neighboring panel expands into the available space, and the layout reorganizes without leaving an empty region.

## Moving panels
Drag a panel by its title bar and drop it onto another panel to exchange their positions.
The entire panel follows the pointer at its original size during the drag, anchored
to the point where its title bar was grabbed. The destination highlight remains
visible to indicate where it can be dropped.
Moving a panel preserves its embedded content and internal state, including any zoom or selection managed by that content. Only its position in the tiling layout changes.

## Independent content
Each panel acts as an independent container for interactive content, such as flowcharts and other visual tools.
Panels can be focused, resized, moved, and closed individually. Their content remains embedded in Arlo's main window, allowing multiple visualizations to coexist without interrupting the conversation.
