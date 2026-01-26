import curses.ascii

# Key Codes
KEY_M_LOWER = ord("m")
KEY_M_UPPER = ord("M")
KEY_ESC = curses.ascii.ESC
KEY_ENTER = curses.ascii.NL
KEY_CTRL_C = curses.ascii.ETX
KEY_SPACE = curses.ascii.SP
KEY_Q_LOWER = ord("q")
KEY_Q_UPPER = ord("Q")
KEY_N_LOWER = ord("n")
KEY_N_UPPER = ord("N")
KEY_B_LOWER = ord("b")
KEY_B_UPPER = ord("B")
KEY_S_LOWER = ord("s")
KEY_S_UPPER = ord("S")
KEY_T_LOWER = ord("t")
KEY_T_UPPER = ord("T")
KEY_A_LOWER = ord("a")
KEY_A_UPPER = ord("A")
KEY_L_LOWER = ord("l")
KEY_L_UPPER = ord("L")
KEY_R_LOWER = ord("r")
KEY_R_UPPER = ord("R")

# UI Layout
MARGIN = 3
FILE_LIST_Y_OFFSET = 3
TRACK_LIST_Y_OFFSET = 5
TRACK_EDITOR_INFO_HEIGHT = 8
APP_TIMEOUT_MS = 200

# Media Preview
SEEK_STEP_SECONDS = 60.0
PREVIEW_DURATION_SECONDS = 30
