import sys
import json
import os
import uuid
from datetime import datetime, timezone
from PySide6 import QtCore, QtWidgets, QtGui
from graph import AtlasGraph


# Define the files where data will be stored
user_data = "user_data.json"
project_data = "project_data.json"

# LOAD DATA
setup_completed = False
projects = []

if os.path.exists(user_data):
    try:
        with open(user_data, "r") as file:
            data = json.load(file)
            setup_completed = data.get("setup_completed", False)
    except Exception as e:
        print(f"Error loading user data: {e}")

if os.path.exists(project_data):
    try:
        with open(project_data, "r") as file:
            data = json.load(file)
            projects = data.get("projects", [])
    except Exception as e:
        print(f"Error loading project data: {e}")


class setup(QtWidgets.QWidget):
    def __init__(self, on_complete_callback):
        super().__init__()
        self.on_complete_callback = on_complete_callback

        # Buttons
        self.button = QtWidgets.QPushButton("Set Project Title")
        self.createProjectButton = QtWidgets.QPushButton("Create Project")

        # Texts
        self.projectTitle = QtWidgets.QLabel("Project Title", alignment=QtCore.Qt.AlignmentFlag.AlignCenter)
        self.setupTitle = QtWidgets.QLabel("ATLAS Setup", alignment=QtCore.Qt.AlignmentFlag.AlignCenter)

        # Types
        self.projectNameBar = QtWidgets.QLineEdit("Type your project title here")
        self.layout = QtWidgets.QVBoxLayout(self)
        self.layout.addWidget(self.setupTitle)
        self.layout.addWidget(self.projectTitle)
        self.layout.addStretch()
        self.layout.addWidget(self.button)
        self.layout.addWidget(self.projectNameBar)
        self.layout.addWidget(self.createProjectButton)

        self.button.clicked.connect(self.nameProject)
        self.createProjectButton.clicked.connect(self.createProject)

    @QtCore.Slot()
    def nameProject(self):
        self.projectTitle.setText(self.projectNameBar.text())

    @QtCore.Slot()
    def createProject(self):
        global setup_completed
        setup_completed = True
        now = datetime.now(timezone.utc).isoformat()
        new_project = {
            "id": str(uuid.uuid4()),
            "name": self.projectNameBar.text(),
            "description": "",
            "status": "active",
            "priority": "medium",
            "created_at": now,
            "updated_at": now,
            "due_date": None,
            "progress": 0,
            "color": "#5288E8",
            "tags": [],
            "tasks": [],
            "notes": [],
            "milestones": [],
            "resources": [],
            "connections": []
        }
        projects.append(new_project)
        save_data()
        self.on_complete_callback()
        self.close()


class selectScreen(QtWidgets.QWidget):
    """The screen that loads if setup_completed is True."""
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Project Selector")
        self.layout = QtWidgets.QVBoxLayout(self)
        self.label = QtWidgets.QLabel("Welcome to your Project Selector!", alignment=QtCore.Qt.AlignmentFlag.AlignCenter)
        self.layout.addWidget(self.label)

        for proj in projects:
            project_name = proj.get("name", "Untitled")
            btn = QtWidgets.QPushButton(project_name)
            # Use a lambda or functools.partial to pass the project_name properly
            btn.clicked.connect(lambda checked, name=project_name: self.openProject(name))
            self.layout.addWidget(btn)

    def openProject(self, project_name):
        global project_win
        project_win = projectScreen(project_name)
        project_win.resize(1450, 900)
        project_win.show()
        self.close()





class projectScreen(QtWidgets.QWidget):
    def __init__(self, project_name):
        super().__init__()

        self.setWindowTitle(f"ATLAS - {project_name}")

        # Find the selected project's saved data
        self.project = next(
            p for p in projects if p["name"] == project_name
        )

        self.layout = QtWidgets.QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)

        # Load the project's knowledge web
        self.graph = AtlasGraph(self.project.get("graph"))
        self.layout.addWidget(self.graph)

        # Save automatically when graph data changes
        self.graph.graph_changed.connect(self.saveGraph)

        # Store the ID of the most recently created node
        self.node_id = None

        # Create Node button
        self.newNode = QtWidgets.QPushButton("Create Node")
        self.layout.addWidget(self.newNode)
        self.newNode.clicked.connect(self.createTestNode)

        # Delete Node button
        self.deleteNodeButton = QtWidgets.QPushButton("Delete Node")
        self.layout.addWidget(self.deleteNodeButton)
        self.deleteNodeButton.clicked.connect(self.deleteTestNode)



    # GENERAL NODE CREATION FUNCTION
    def createNode(
        self,
        name,
        color=None,
        group="",
        connections=None,
        node_type="note",
        description="",
        x=None,
        y=None,
        radius=None,
        metadata=None
    ):
        return self.graph.create_node(
            name,
            color=color,
            group=group,
            connections=connections,
            node_type=node_type,
            description=description,
            x=x,
            y=y,
            radius=radius,
            metadata=metadata
        )

    # SAVE GRAPH DATA
    def saveGraph(self):
        self.project["graph"] = self.graph.get_graph_data()
        save_data()



    def saveGraph(self):
        self.project["graph"] = self.graph.get_graph_data()
        save_data()

    def createNode(
        self,
        name,
        color=None,
        group="",
        connections=None,
        node_type="note",
        description="",
        x=None,
        y=None,
        radius=None,
        metadata=None
    ):
        return self.graph.create_node(
            name,
            color=color,
            group=group,
            connections=connections,
            node_type=node_type,
            description=description,
            x=x,
            y=y,
            radius=radius,
            metadata=metadata
        )

    def connectNodes(self, node_a, node_b, relation="related_to"):
        self.graph.connect_nodes(
            node_a,
            node_b,
            relation=relation
        )

    def focusNode(self, node_id, zoom=1.5):
        self.graph.focus_node(node_id, zoom)


def launch_select_screen():
    """Helper function to cleanly open the main window."""
    global select_win
    select_win = selectScreen()
    select_win.resize(800, 600)
    select_win.show()


def save_data():
    """Save user settings and project information separately."""
    with open(user_data, "w") as file:
        json.dump({"setup_completed": setup_completed}, file, indent=4)
    with open(project_data, "w") as file:
        json.dump({"projects": projects}, file, indent=4)
    print("Progress saved completely.")


if __name__ == "__main__":
    app = QtWidgets.QApplication([])
    if setup_completed:
        launch_select_screen()
    else:
        setup_widget = setup(on_complete_callback=launch_select_screen)
        setup_widget.resize(800, 600)
        setup_widget.show()
    exit_code = app.exec()
    save_data()
    sys.exit(exit_code)
