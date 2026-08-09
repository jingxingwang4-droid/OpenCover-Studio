APP_QSS = r"""
* { font-family: "Microsoft YaHei UI", "Segoe UI"; font-size: 13px; color: #20252b; }
QMainWindow, QWidget#Root { background: #f5f5f2; }
QWidget#ContentPage { background: rgba(248, 249, 247, 232); }
QFrame#Sidebar { background: #253238; border: none; }
QLabel#Brand { color: white; font-size: 20px; font-weight: 700; padding: 18px 16px 12px; }
QLabel#SidebarStatus { color: #bac7cc; font-size: 11px; padding: 10px 16px; }
QPushButton#NavButton { text-align: left; color: #dbe3e6; background: transparent; border: 0; border-radius: 5px; padding: 10px 16px; margin: 1px 8px; }
QPushButton#NavButton:hover { background: #33454d; }
QPushButton#NavButton:checked { color: white; background: #3f5962; font-weight: 600; border-left: 3px solid #5da8a0; }
QLabel#PageTitle { font-size: 24px; font-weight: 700; color: #172126; }
QLabel#PageSubtitle { color: #657178; }
QFrame#Panel { background: white; border: 1px solid #dfe3e2; border-radius: 7px; }
QFrame#Hero { background: #eef3f0; border: 1px solid #d3ded9; border-radius: 8px; }
QLabel#CardTitle { font-size: 17px; font-weight: 650; }
QLabel#Muted { color: #6c777d; }
QPushButton { background: #ffffff; border: 1px solid #bdc7c9; border-radius: 5px; padding: 7px 13px; }
QPushButton:hover { border-color: #6d8589; background: #f8faf9; }
QPushButton#Primary { background: #287a72; color: white; border-color: #287a72; font-weight: 600; padding: 9px 18px; }
QPushButton#Primary:hover { background: #226a64; }
QPushButton:disabled { color: #9da5a8; background: #eef0ef; border-color: #d9dddc; }
QLineEdit, QTextEdit, QComboBox, QSpinBox { background: white; border: 1px solid #bcc5c7; border-radius: 4px; padding: 7px; selection-background-color: #4b8c85; }
QLineEdit:focus, QTextEdit:focus, QComboBox:focus, QSpinBox:focus { border-color: #287a72; }
QTableWidget { background: white; border: 1px solid #d8dddd; gridline-color: #ebeeee; }
QHeaderView::section { background: #edf0ef; border: 0; border-bottom: 1px solid #d2d8d7; padding: 7px; font-weight: 600; }
QProgressBar { border: 1px solid #cbd1d1; border-radius: 4px; text-align: center; background: #eff1f0; }
QProgressBar::chunk { background: #4b8c85; }
QScrollArea { border: 0; background: transparent; }
QToolTip { color: #20252b; background: #fff; border: 1px solid #bdc7c9; }
"""
