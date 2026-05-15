#!/usr/bin/env python3
"""Simple Tkinter GUI for the WorldClim downloader."""

from __future__ import annotations

import queue
import subprocess
import sys
import threading
from pathlib import Path
from tkinter import BooleanVar, StringVar, Tk, filedialog, messagebox
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText


SCRIPT_PATH = Path(__file__).with_name("download_worldclim.py")
RESOLUTIONS = ("all", "10m", "5m", "2.5m", "30s")


class WorldClimGUI:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title("WorldClim/BioClim Downloader")
        self.root.geometry("920x680")
        self.root.minsize(780, 560)

        self.output_dir = StringVar(value="worldclim_archive")
        self.resolution = StringVar(value="all")
        self.model = StringVar(value="MIROC6")
        self.scenario = StringVar(value="ssp245")
        self.download_current = BooleanVar(value=True)
        self.download_bioclim = BooleanVar(value=True)
        self.download_future = BooleanVar(value=True)
        self.retries = StringVar(value="4")
        self.timeout = StringVar(value="60")

        self.process: subprocess.Popen[str] | None = None
        self.output_queue: queue.Queue[str] = queue.Queue()

        self._build_ui()
        self.root.after(100, self._drain_output_queue)

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(2, weight=1)

        options = ttk.Frame(self.root, padding=12)
        options.grid(row=0, column=0, sticky="ew")
        options.columnconfigure(1, weight=1)
        options.columnconfigure(3, weight=1)

        ttk.Label(options, text="Output folder").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(options, textvariable=self.output_dir).grid(row=0, column=1, columnspan=2, sticky="ew", pady=4)
        ttk.Button(options, text="Browse", command=self._browse_output).grid(row=0, column=3, sticky="e", padx=(8, 0), pady=4)

        ttk.Label(options, text="Datasets").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
        dataset_frame = ttk.Frame(options)
        dataset_frame.grid(row=1, column=1, columnspan=3, sticky="w", pady=4)
        ttk.Checkbutton(dataset_frame, text="Current base", variable=self.download_current).grid(row=0, column=0, padx=(0, 16))
        ttk.Checkbutton(dataset_frame, text="Current BioClim", variable=self.download_bioclim).grid(row=0, column=1, padx=(0, 16))
        ttk.Checkbutton(dataset_frame, text="Future CMIP6", variable=self.download_future).grid(row=0, column=2)

        ttk.Label(options, text="Resolution").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Combobox(options, textvariable=self.resolution, values=RESOLUTIONS, state="readonly", width=12).grid(
            row=2, column=1, sticky="w", pady=4
        )
        ttk.Label(options, text="Future model").grid(row=2, column=2, sticky="e", padx=(16, 8), pady=4)
        ttk.Entry(options, textvariable=self.model, width=24).grid(row=2, column=3, sticky="ew", pady=4)

        ttk.Label(options, text="Scenario").grid(row=3, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(options, textvariable=self.scenario, width=14).grid(row=3, column=1, sticky="w", pady=4)
        ttk.Label(options, text="Retries").grid(row=3, column=2, sticky="e", padx=(16, 8), pady=4)
        retry_frame = ttk.Frame(options)
        retry_frame.grid(row=3, column=3, sticky="ew", pady=4)
        ttk.Entry(retry_frame, textvariable=self.retries, width=8).grid(row=0, column=0, sticky="w")
        ttk.Label(retry_frame, text="Timeout").grid(row=0, column=1, sticky="w", padx=(18, 8))
        ttk.Entry(retry_frame, textvariable=self.timeout, width=8).grid(row=0, column=2, sticky="w")

        buttons = ttk.Frame(self.root, padding=(12, 0, 12, 8))
        buttons.grid(row=1, column=0, sticky="ew")
        self.dry_run_button = ttk.Button(buttons, text="Dry Run", command=lambda: self._start(dry_run=True))
        self.dry_run_button.grid(row=0, column=0, padx=(0, 8))
        self.download_button = ttk.Button(buttons, text="Download", command=lambda: self._start(dry_run=False))
        self.download_button.grid(row=0, column=1, padx=(0, 8))
        self.stop_button = ttk.Button(buttons, text="Stop", command=self._stop, state="disabled")
        self.stop_button.grid(row=0, column=2, padx=(0, 8))
        ttk.Button(buttons, text="Clear Log", command=lambda: self.log.delete("1.0", "end")).grid(row=0, column=3)

        self.status = StringVar(value="Ready")
        ttk.Label(buttons, textvariable=self.status).grid(row=0, column=4, sticky="e", padx=(20, 0))
        buttons.columnconfigure(4, weight=1)

        self.log = ScrolledText(self.root, wrap="word", height=28)
        self.log.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 12))

    def _browse_output(self) -> None:
        selected = filedialog.askdirectory(initialdir=str(Path.cwd()))
        if selected:
            self.output_dir.set(selected)

    def _build_command(self, dry_run: bool) -> list[str]:
        if not any((self.download_current.get(), self.download_bioclim.get(), self.download_future.get())):
            raise ValueError("Select at least one dataset.")

        command = [sys.executable, "-u", str(SCRIPT_PATH)]
        if self.download_current.get():
            command.append("--current")
        if self.download_bioclim.get():
            command.append("--bioclim")
        if self.download_future.get():
            command.append("--future")
        if dry_run:
            command.append("--dry-run")

        command.extend(
            [
                "--output",
                self.output_dir.get().strip() or "worldclim_archive",
                "--resolution",
                self.resolution.get(),
                "--model",
                self.model.get().strip() or "MIROC6",
                "--scenario",
                self.scenario.get().strip() or "ssp245",
                "--retries",
                self.retries.get().strip() or "4",
                "--timeout",
                self.timeout.get().strip() or "60",
                "--no-progress",
            ]
        )
        return command

    def _start(self, dry_run: bool) -> None:
        if self.process is not None:
            messagebox.showinfo("Downloader running", "A download task is already running.")
            return

        try:
            command = self._build_command(dry_run)
        except ValueError as exc:
            messagebox.showerror("Missing option", str(exc))
            return

        self._append_log("$ " + " ".join(command) + "\n\n")
        self.status.set("Running dry run..." if dry_run else "Downloading...")
        self._set_running(True)

        thread = threading.Thread(target=self._run_command, args=(command,), daemon=True)
        thread.start()

    def _run_command(self, command: list[str]) -> None:
        try:
            self.process = subprocess.Popen(
                command,
                cwd=SCRIPT_PATH.parent,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            assert self.process.stdout is not None
            for line in self.process.stdout:
                self.output_queue.put(line)
            return_code = self.process.wait()
            self.output_queue.put(f"\nProcess exited with code {return_code}.\n")
        except Exception as exc:
            self.output_queue.put(f"\nGUI failed to start downloader: {exc}\n")
        finally:
            self.process = None
            self.output_queue.put("__WORLDCLIM_GUI_DONE__")

    def _stop(self) -> None:
        if self.process is not None:
            self.process.terminate()
            self.status.set("Stopping...")

    def _drain_output_queue(self) -> None:
        while True:
            try:
                message = self.output_queue.get_nowait()
            except queue.Empty:
                break
            if message == "__WORLDCLIM_GUI_DONE__":
                self.status.set("Ready")
                self._set_running(False)
            else:
                self._append_log(message)
        self.root.after(100, self._drain_output_queue)

    def _append_log(self, text: str) -> None:
        self.log.insert("end", text)
        self.log.see("end")

    def _set_running(self, running: bool) -> None:
        state = "disabled" if running else "normal"
        self.dry_run_button.configure(state=state)
        self.download_button.configure(state=state)
        self.stop_button.configure(state="normal" if running else "disabled")


def main() -> None:
    root = Tk()
    WorldClimGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
