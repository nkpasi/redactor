import os
import queue
import re
import threading
import tkinter as tk
from collections import Counter
from dataclasses import dataclass
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

PALETTE = [
    "#f87171", "#34d399", "#60a5fa", "#a78bfa", "#f472b6",
    "#fb923c", "#2dd4bf", "#a3e635", "#e879f9", "#38bdf8",
]
BLOCK = "\u2588" * 8
CHECKED = "\u2611"
UNCHECKED = "\u2610"


@dataclass
class Finding:
    fid: int
    kind: str
    start: int
    end: int
    score: float
    selected: bool = True


class RedactorApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Local Redactor")
        self.geometry("1280x780")
        self.minsize(1050, 640)

        # Engine and threading
        self.analyzer = None
        self.q = queue.Queue()
        self.scan_token = 0
        self.pending_scan = False

        # Document state
        self.source = ""
        self.source_path = None
        self.scanned_source = None
        self.findings = []
        self.next_id = 1
        self.min_score = 0.35
        self.mode = "Edit"

        # UI state
        self.colors = {"CUSTOM": "#facc15"}
        self.type_vars = {}
        self.slider_job = None

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.build_toolbar()
        self.build_main()
        self.build_status()

        self.bind("<Control-o>", lambda e: self.open_file())
        self.bind("<Control-s>", lambda e: self.save_file())

        self.set_status("Loading the local language model (first start takes a few seconds)...")
        threading.Thread(target=self.load_engine, daemon=True).start()
        self.after(100, self.poll)

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------
    def build_toolbar(self):
        bar = ctk.CTkFrame(self, corner_radius=0)
        bar.grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(
            bar, text="Local Redactor", font=ctk.CTkFont(size=18, weight="bold")
        ).pack(side="left", padx=(16, 14), pady=10)
        ctk.CTkButton(bar, text="Open file", width=96, command=self.open_file).pack(side="left", padx=4)
        ctk.CTkButton(bar, text="Scan", width=80, command=self.scan_clicked).pack(side="left", padx=4)
        self.seg = ctk.CTkSegmentedButton(
            bar, values=["Edit", "Review", "Preview"], command=self.set_mode
        )
        self.seg.set("Edit")
        self.seg.pack(side="left", padx=16)
        ctk.CTkLabel(bar, text="100% offline", text_color="#34d399").pack(side="right", padx=16)

    def build_main(self):
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.grid(row=1, column=0, sticky="nsew", padx=10, pady=(6, 6))
        main.grid_columnconfigure(0, weight=1)
        main.grid_columnconfigure(1, weight=0)
        main.grid_rowconfigure(0, weight=1)

        self.tb = ctk.CTkTextbox(
            main, font=ctk.CTkFont(family="Consolas", size=14), wrap="word", corner_radius=10
        )
        self.tb.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.txt = self.tb._textbox  # the underlying Tk text widget, needed for tags
        self.txt.configure(selectbackground="#2f6feb", selectforeground="#ffffff")
        self.txt.tag_config("current", underline=True)

        right = ctk.CTkFrame(main, width=430, corner_radius=10)
        right.grid(row=0, column=1, sticky="nsew")
        right.pack_propagate(False)
        self.build_right(right)

    def build_right(self, right):
        bold = ctk.CTkFont(size=13, weight="bold")

        # Bottom items are packed first so they stay pinned to the bottom.
        actions = ctk.CTkFrame(right, fg_color="transparent")
        actions.pack(side="bottom", fill="x", padx=12, pady=(4, 12))
        ctk.CTkButton(
            actions, text="Save redacted file", height=36, command=self.save_file
        ).pack(side="left", expand=True, fill="x", padx=(0, 6))
        ctk.CTkButton(
            actions, text="Copy", width=80, height=36,
            fg_color="#374151", hover_color="#4b5563", command=self.copy_result,
        ).pack(side="left")

        style_row = ctk.CTkFrame(right, fg_color="transparent")
        style_row.pack(side="bottom", fill="x", padx=12, pady=(6, 4))
        ctk.CTkLabel(style_row, text="Replace with").pack(side="left")
        self.style_var = ctk.StringVar(value="Type label")
        ctk.CTkOptionMenu(
            style_row, values=["Type label", "Black block", "[REDACTED]"],
            variable=self.style_var, command=self.on_style_change, width=170,
        ).pack(side="right")

        # Entity types
        ctk.CTkLabel(right, text="Entity types (tick = redact)", font=bold).pack(
            anchor="w", padx=14, pady=(12, 2)
        )
        self.types_frame = ctk.CTkScrollableFrame(right, height=120)
        self.types_frame.pack(fill="x", padx=12)

        # Confidence slider
        self.conf_label = ctk.CTkLabel(right, text=f"Minimum confidence: {self.min_score:.2f}")
        self.conf_label.pack(anchor="w", padx=14, pady=(10, 0))
        slider = ctk.CTkSlider(right, from_=0, to=0.95, number_of_steps=19, command=self.on_slider)
        slider.set(self.min_score)
        slider.pack(fill="x", padx=14, pady=(2, 4))

        # Custom term
        ctk.CTkLabel(right, text="Add custom terms (comma separated)", font=bold).pack(
            anchor="w", padx=14, pady=(8, 2)
        )
        term_row = ctk.CTkFrame(right, fg_color="transparent")
        term_row.pack(fill="x", padx=12)
        self.term_entry = ctk.CTkEntry(term_row, placeholder_text="e.g. Project Falcon")
        self.term_entry.pack(side="left", expand=True, fill="x", padx=(0, 6))
        self.term_entry.bind("<Return>", lambda e: self.add_terms())
        ctk.CTkButton(term_row, text="Add", width=60, command=self.add_terms).pack(side="left")

        # Bulk buttons
        bulk = ctk.CTkFrame(right, fg_color="transparent")
        bulk.pack(fill="x", padx=12, pady=(8, 0))
        ctk.CTkButton(bulk, text="Select all", width=90, command=lambda: self.set_all(True)).pack(side="left", padx=(0, 6))
        ctk.CTkButton(bulk, text="Select none", width=90, command=lambda: self.set_all(False)).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            bulk, text="Redact highlighted text", command=self.redact_selection,
            fg_color="#7c3aed", hover_color="#6d28d9",
        ).pack(side="left", expand=True, fill="x")

        # Findings list
        tree_box = ctk.CTkFrame(right, fg_color="transparent")
        tree_box.pack(fill="both", expand=True, padx=12, pady=8)
        tree_box.grid_rowconfigure(0, weight=1)
        tree_box.grid_columnconfigure(0, weight=1)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Treeview", background="#1f2328", fieldbackground="#1f2328",
            foreground="#e5e7eb", rowheight=26, borderwidth=0, font=("Segoe UI", 10),
        )
        style.configure(
            "Treeview.Heading", background="#2b3138", foreground="#e5e7eb",
            relief="flat", font=("Segoe UI", 10, "bold"),
        )
        style.map(
            "Treeview",
            background=[("selected", "#2f6feb")],
            foreground=[("selected", "#ffffff")],
        )

        self.tree = ttk.Treeview(
            tree_box, columns=("sel", "kind", "text", "score"),
            show="headings", selectmode="browse",
        )
        for col, title, width, anchor in [
            ("sel", "", 36, "center"), ("kind", "Type", 112, "w"),
            ("text", "Text", 170, "w"), ("score", "Conf.", 52, "center"),
        ]:
            self.tree.heading(col, text=title)
            self.tree.column(col, width=width, anchor=anchor, stretch=(col == "text"))
        self.tree.tag_configure("off", foreground="#6b7280")
        scroll = ctk.CTkScrollbar(tree_box, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<Button-1>", self.on_tree_click)
        self.tree.bind("<space>", self.on_tree_space)

    def build_status(self):
        self.status = ctk.CTkLabel(self, text="", anchor="w", text_color="#9ca3af")
        self.status.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 8))

    def set_status(self, message):
        self.status.configure(text=message)

    # ------------------------------------------------------------------
    # Engine loading and scanning (background threads)
    # ------------------------------------------------------------------
    def load_engine(self):
        try:
            from presidio_analyzer import AnalyzerEngine
            self.analyzer = AnalyzerEngine()
            self.q.put(("ready",))
        except Exception as e:
            self.q.put(("engine_error", str(e)))

    def start_scan(self):
        if self.analyzer is None:
            self.pending_scan = True
            self.set_status("Model is still loading. The scan will start automatically.")
            return
        self.scan_token += 1
        token = self.scan_token
        src = self.source
        self.set_status("Scanning locally...")

        def work():
            try:
                results = self.analyzer.analyze(text=src, language="en")
                self.q.put(("scan_done", token, src, results))
            except Exception as e:
                self.q.put(("scan_error", token, str(e)))

        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        try:
            while True:
                msg = self.q.get_nowait()
                kind = msg[0]
                if kind == "ready":
                    self.set_status("Ready. Open a file or paste text, then click Scan.")
                    if self.pending_scan:
                        self.pending_scan = False
                        self.start_scan()
                elif kind == "engine_error":
                    self.set_status("Scanner failed to start.")
                    messagebox.showerror(
                        "Scanner failed to start",
                        f"{msg[1]}\n\nIf the language model is missing, run:\n"
                        "python -m spacy download en_core_web_lg",
                    )
                elif kind == "scan_error":
                    if msg[1] == self.scan_token:
                        self.set_status("Scan failed.")
                        messagebox.showerror("Scan failed", msg[2])
                elif kind == "scan_done":
                    _, token, src, results = msg
                    if token == self.scan_token:
                        self.apply_results(src, results)
        except queue.Empty:
            pass
        self.after(100, self.poll)

    def apply_results(self, src, results):
        best = {}
        for r in results:
            key = (r.start, r.end)
            if key not in best or r.score > best[key].score:
                best[key] = r
        self.scanned_source = src
        self.findings = []
        for r in sorted(best.values(), key=lambda r: (r.start, -r.end)):
            self.findings.append(
                Finding(self.new_id(), r.entity_type, r.start, r.end, float(r.score))
            )
        self.render()
        if not self.findings:
            self.set_status("The scanner found nothing. You can still add custom terms.")

    # ------------------------------------------------------------------
    # Modes and rendering
    # ------------------------------------------------------------------
    def new_id(self):
        self.next_id += 1
        return self.next_id

    def color_for(self, kind):
        if kind not in self.colors:
            self.colors[kind] = PALETTE[len(self.colors) % len(PALETTE)]
        return self.colors[kind]

    def visible(self):
        return sorted(
            (f for f in self.findings if f.score >= self.min_score),
            key=lambda f: f.start,
        )

    def scan_clicked(self):
        self.set_mode("Review", force=True)

    def set_mode(self, value, force=False, capture=True):
        if self.mode == "Edit" and capture:
            text = self.txt.get("1.0", "end-1c")
            if text != self.source:
                self.source = text
                self.findings = []
                self.scanned_source = None
        self.mode = value
        self.seg.set(value)

        if value == "Edit":
            self.render()
            return
        if not self.source.strip():
            self.mode = "Edit"
            self.seg.set("Edit")
            self.render()
            self.set_status("Nothing to scan. Paste text or open a file first.")
            return

        needs_scan = force or self.scanned_source != self.source
        if needs_scan:
            self.findings = []
        self.render()
        if needs_scan:
            self.start_scan()

    def clear_tags(self):
        for tag in self.txt.tag_names():
            if tag.startswith(("find_", "lbl_")):
                self.txt.tag_delete(tag)

    def render(self):
        if self.mode == "Edit":
            self.render_edit()
        elif self.mode == "Review":
            self.render_review()
        else:
            self.render_preview()
        self.refresh_list()
        self.rebuild_types()
        if self.findings:
            self.update_status()

    def render_edit(self):
        self.txt.configure(state="normal")
        self.clear_tags()
        self.txt.delete("1.0", "end")
        self.txt.insert("1.0", self.source)

    def render_review(self):
        self.txt.configure(state="normal")
        self.clear_tags()
        self.txt.delete("1.0", "end")
        self.txt.insert("1.0", self.source)
        for f in self.visible():
            tag = f"find_{f.fid}"
            self.txt.tag_add(tag, f"1.0+{f.start}c", f"1.0+{f.end}c")
            self.style_tag(f)
            self.txt.tag_bind(tag, "<ButtonRelease-1>", lambda e, i=f.fid: self.on_text_click(i))
            self.txt.tag_bind(tag, "<Enter>", lambda e: self.txt.configure(cursor="hand2"))
            self.txt.tag_bind(tag, "<Leave>", lambda e: self.txt.configure(cursor="xterm"))
        self.txt.tag_raise("current")
        self.txt.tag_raise("sel")
        self.txt.configure(state="disabled")

    def style_tag(self, f):
        tag = f"find_{f.fid}"
        color = self.color_for(f.kind)
        if f.selected:
            self.txt.tag_config(tag, background=color, foreground="#0b0f14", underline=False)
        else:
            self.txt.tag_config(
                tag, background="", foreground="#e5e7eb", underline=True, underlinefg=color
            )

    def replacement(self, f):
        choice = self.style_var.get()
        if choice == "Black block":
            return BLOCK
        if choice == "[REDACTED]":
            return "[REDACTED]"
        return f"[{f.kind}]"

    def build_segments(self):
        chosen = sorted(
            (f for f in self.findings if f.selected and f.score >= self.min_score),
            key=lambda f: (f.start, -(f.end - f.start)),
        )
        segments, pos = [], 0
        for f in chosen:
            if f.start < pos:
                continue
            if f.start > pos:
                segments.append((self.source[pos:f.start], None))
            segments.append((self.replacement(f), f.kind))
            pos = f.end
        segments.append((self.source[pos:], None))
        return segments

    def render_preview(self):
        self.txt.configure(state="normal")
        self.clear_tags()
        self.txt.delete("1.0", "end")
        for text, kind in self.build_segments():
            if kind is None:
                self.txt.insert("end", text)
            else:
                tag = f"lbl_{kind}"
                self.txt.tag_config(tag, background=self.color_for(kind), foreground="#0b0f14")
                self.txt.insert("end", text, (tag,))
        self.txt.tag_raise("sel")
        self.txt.configure(state="disabled")

    def on_style_change(self, _value):
        if self.mode == "Preview":
            self.render_preview()

    # ------------------------------------------------------------------
    # Findings list and type panel
    # ------------------------------------------------------------------
    def row_values(self, f):
        snippet = self.source[f.start:f.end].replace("\n", " ")
        if len(snippet) > 40:
            snippet = snippet[:37] + "..."
        return (CHECKED if f.selected else UNCHECKED, f.kind, snippet, f"{f.score:.2f}")

    def row_tags(self, f):
        if not f.selected:
            return ("off",)
        tag = f"k_{f.kind}"
        self.tree.tag_configure(tag, foreground=self.color_for(f.kind))
        return (tag,)

    def refresh_list(self):
        self.tree.delete(*self.tree.get_children())
        for f in self.visible():
            self.tree.insert(
                "", "end", iid=str(f.fid), values=self.row_values(f), tags=self.row_tags(f)
            )

    def rebuild_types(self):
        for widget in self.types_frame.winfo_children():
            widget.destroy()
        self.type_vars = {}
        vis = self.visible()
        counts = Counter(f.kind for f in vis)
        for kind, n in sorted(counts.items()):
            var = ctk.BooleanVar(value=all(f.selected for f in vis if f.kind == kind))
            self.type_vars[kind] = var
            ctk.CTkCheckBox(
                self.types_frame, text=f"{kind}  ({n})", variable=var,
                fg_color=self.color_for(kind), hover_color=self.color_for(kind),
                command=lambda k=kind, v=var: self.set_type(k, v.get()),
            ).pack(anchor="w", pady=3, padx=4)

    def update_status(self):
        vis = self.visible()
        chosen = sum(1 for f in vis if f.selected)
        hidden = len(self.findings) - len(vis)
        self.set_status(
            f"{len(vis)} findings shown  |  {chosen} will be redacted  |  "
            f"{hidden} hidden by the confidence filter"
        )

    def refresh_states(self):
        vis = self.visible()
        if self.mode == "Preview":
            self.render_preview()
        for f in vis:
            iid = str(f.fid)
            if self.tree.exists(iid):
                self.tree.item(iid, values=self.row_values(f), tags=self.row_tags(f))
            if self.mode == "Review":
                self.style_tag(f)
        for kind, var in self.type_vars.items():
            items = [f for f in vis if f.kind == kind]
            var.set(bool(items) and all(f.selected for f in items))
        self.update_status()

    # ------------------------------------------------------------------
    # Interaction
    # ------------------------------------------------------------------
    def toggle(self, fid):
        for f in self.findings:
            if f.fid == fid:
                f.selected = not f.selected
                break
        self.refresh_states()

    def set_type(self, kind, value):
        for f in self.visible():
            if f.kind == kind:
                f.selected = bool(value)
        self.refresh_states()

    def set_all(self, value):
        for f in self.visible():
            f.selected = value
        self.refresh_states()

    def find_by_id(self, fid):
        for f in self.findings:
            if f.fid == fid:
                return f
        return None

    def jump_to(self, f):
        if self.mode != "Review":
            return
        self.txt.see(f"1.0+{f.start}c")
        self.txt.tag_remove("current", "1.0", "end")
        self.txt.tag_add("current", f"1.0+{f.start}c", f"1.0+{f.end}c")

    def on_tree_click(self, event):
        row = self.tree.identify_row(event.y)
        if not row:
            return
        f = self.find_by_id(int(row))
        if f is None:
            return
        if self.tree.identify_column(event.x) == "#1":
            self.toggle(f.fid)
        self.tree.selection_set(row)
        self.jump_to(f)

    def on_tree_space(self, _event):
        selection = self.tree.selection()
        if selection:
            self.toggle(int(selection[0]))
        return "break"

    def on_text_click(self, fid):
        # Ignore the click if the user was dragging to select text.
        if self.txt.tag_ranges("sel"):
            return
        self.toggle(fid)
        if self.tree.exists(str(fid)):
            self.tree.selection_set(str(fid))
            self.tree.see(str(fid))

    def on_slider(self, value):
        self.min_score = round(float(value), 2)
        self.conf_label.configure(text=f"Minimum confidence: {self.min_score:.2f}")
        if self.slider_job:
            self.after_cancel(self.slider_job)
        self.slider_job = self.after(250, self.render)

    def add_span(self, start, end, kind, score=1.0):
        self.findings = [f for f in self.findings if f.end <= start or f.start >= end]
        self.findings.append(Finding(self.new_id(), kind, start, end, score))

    def add_terms(self):
        raw = self.term_entry.get().strip()
        if not raw:
            return
        if self.mode == "Edit" or self.scanned_source != self.source:
            self.set_status("Scan the text first, then add custom terms.")
            return
        added = 0
        for term in [t.strip() for t in raw.split(",") if t.strip()]:
            for m in re.finditer(re.escape(term), self.source, re.IGNORECASE):
                self.add_span(m.start(), m.end(), "CUSTOM")
                added += 1
        self.term_entry.delete(0, "end")
        self.render()
        self.set_status(f"Added {added} custom match(es)." if added else "No matches found for that term.")

    def redact_selection(self):
        if self.mode != "Review":
            self.set_status("Switch to Review, drag over some text, then click this button.")
            return
        try:
            first = self.txt.index("sel.first")
            last = self.txt.index("sel.last")
        except tk.TclError:
            self.set_status("Drag over some text in the document first.")
            return
        start = len(self.txt.get("1.0", first))
        end = len(self.txt.get("1.0", last))
        chunk = self.source[start:end]
        start += len(chunk) - len(chunk.lstrip())
        end -= len(chunk) - len(chunk.rstrip())
        if end <= start:
            return
        self.add_span(start, end, "CUSTOM")
        self.txt.tag_remove("sel", "1.0", "end")
        self.render()
        self.set_status("Added your highlighted text as a CUSTOM redaction.")

    # ------------------------------------------------------------------
    # Files and output
    # ------------------------------------------------------------------
    def open_file(self):
        path = filedialog.askopenfilename(
            title="Choose a text file",
            filetypes=[
                ("Text files", "*.txt *.log *.md *.csv *.json *.py *.env"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read()
        except UnicodeDecodeError:
            messagebox.showerror("Cannot open", "This is not a plain UTF-8 text file.")
            return
        except OSError as e:
            messagebox.showerror("Cannot open", str(e))
            return
        self.source = text
        self.source_path = path
        self.scanned_source = None
        self.findings = []
        self.set_mode("Review", force=True, capture=False)

    def ready_for_output(self):
        if self.mode == "Edit" or self.scanned_source != self.source or not self.source:
            messagebox.showinfo("Scan first", "Click Scan before saving or copying.")
            return False
        return True

    def result_text(self):
        return "".join(text for text, _ in self.build_segments())

    def save_file(self):
        if not self.ready_for_output():
            return
        if not any(f.selected and f.score >= self.min_score for f in self.findings):
            if not messagebox.askyesno("Nothing selected", "No items are selected. Save an unchanged copy?"):
                return
        if self.source_path:
            folder = os.path.dirname(self.source_path)
            name, ext = os.path.splitext(os.path.basename(self.source_path))
            initial = f"{name}_REDACTED{ext}"
        else:
            folder, initial = os.getcwd(), "redacted.txt"
        path = filedialog.asksaveasfilename(
            title="Save redacted file", initialdir=folder, initialfile=initial,
            defaultextension=".txt", filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self.result_text())
        except OSError as e:
            messagebox.showerror("Cannot save", str(e))
            return
        self.set_status(f"Saved: {path}")

    def copy_result(self):
        if not self.ready_for_output():
            return
        self.clipboard_clear()
        self.clipboard_append(self.result_text())
        self.set_status("Redacted text copied to the clipboard.")


if __name__ == "__main__":
    RedactorApp().mainloop()