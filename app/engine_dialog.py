"""Folder chooser run in a separate process (`server.py --pick-folder <initial> <outfile>`)."""


def run(initial, outfile):
    import tkinter as tk
    from tkinter import filedialog
    r = tk.Tk()
    r.withdraw()
    r.attributes("-topmost", 1)
    p = filedialog.askdirectory(initialdir=initial, title="Choose download folder")
    with open(outfile, "w", encoding="utf-8") as f:
        f.write(p or "")


def run_file(initial, outfile):
    import tkinter as tk
    from tkinter import filedialog
    r = tk.Tk()
    r.withdraw()
    r.attributes("-topmost", 1)
    p = filedialog.askopenfilename(initialdir=initial, title="Choose your cookies.txt file",
                                   filetypes=[("Cookies file", "*.txt"), ("All files", "*.*")])
    with open(outfile, "w", encoding="utf-8") as f:
        f.write(p or "")
