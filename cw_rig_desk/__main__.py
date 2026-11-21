import sys
import tkinter as tk

from cw_rig_desk.app import App


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test":
        from cw_rig_desk.self_test import run
        return run(sys.argv[2])
    root = tk.Tk()
    App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
