import os
import sys
import subprocess
import customtkinter as ctk

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class POEStickLauncher(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("POEStick Launcher")
        self.geometry("460x900")
        self.resizable(False, False)

        # ── Header ──────────────────────────────────────────────────────────
        ctk.CTkLabel(
            self,
            text="POEStick",
            font=ctk.CTkFont(family="Arial", size=32, weight="bold"),
            text_color="#00D2FF",
        ).pack(pady=(24, 2))

        ctk.CTkLabel(
            self,
            text="PoE 3.28 Mirage  •  Arbitrage & Trade Analyzer",
            font=ctk.CTkFont(family="Arial", size=12),
            text_color="gray",
        ).pack(pady=(0, 16))

        # ── Primary actions (always visible) ────────────────────────────────
        ctk.CTkButton(
            self,
            text="⚡  Launch Live Scanner",
            font=ctk.CTkFont(size=15, weight="bold"),
            height=46,
            command=self.launch_live_scanner,
        ).pack(pady=(0, 6), padx=36, fill="x")

        ctk.CTkButton(
            self,
            text="📊  Run Single Scan",
            font=ctk.CTkFont(size=13),
            fg_color="#2b2b2b",
            hover_color="#3a3a3a",
            height=36,
            command=self.launch_single_scan,
        ).pack(pady=(0, 14), padx=56, fill="x")

        # ── Scrollable analyzer section ──────────────────────────────────────
        scroll = ctk.CTkScrollableFrame(self, label_text="Analyzers", height=620)
        scroll.pack(padx=20, pady=(0, 10), fill="both", expand=True)

        # Helper — adds a section header inside the scroll frame
        def section(label: str, color: str = "#555555"):
            ctk.CTkLabel(
                scroll,
                text=label,
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=color,
                anchor="w",
            ).pack(fill="x", padx=4, pady=(12, 2))

        # Helper — adds a standard analyzer button
        def btn(text: str, cmd, highlight: bool = False):
            fg = "#1a3a2a" if highlight else "#2b2b2b"
            hv = "#2a5a3a" if highlight else "#3a3a3a"
            ctk.CTkButton(
                scroll,
                text=text,
                font=ctk.CTkFont(size=13),
                fg_color=fg,
                hover_color=hv,
                height=38,
                anchor="w",
                command=cmd,
            ).pack(pady=3, padx=4, fill="x")

        # ── 3.28 NEW ─────────────────────────────────────────────────────────
        section("✦  3.28 MIRAGE  —  NEW", color="#00D2FF")
        btn("⛏️  Fossil Price Index + Delve ROI",    self.launch_fossils,         highlight=True)
        btn("🌐  Astrolabe → Memory Vault ROI",       self.launch_astrolabes,      highlight=True)
        btn("🏰  Breach Fortress Combo Analyzer",     self.launch_breach_fortress, highlight=True)
        btn("🌿  Harvest + Lifeforce + Catalysts",   self.launch_harvest,         highlight=True)
        btn("📦  Strongbox → Operative ROI",          self.launch_strongbox,       highlight=True)

        # ── Market Arbitrage ─────────────────────────────────────────────────
        section("Market Arbitrage")
        btn("⚡  Supply Shock Detector",              self.launch_supply_shock)
        btn("🎴  Divination Card Arbitrage",          self.launch_div_cards)
        btn("💎  Gem Arbitrage  (Awakened / Alt-Qual)", self.launch_gem_arbitrage)
        btn("🃏  Stacked Deck EV  + Cloister Scarab", self.launch_stacked_deck)
        btn("💰  Gold Squeeze Advisor  (Faustus vs Trade)", self.launch_gold_squeeze)

        # ── Crafting ─────────────────────────────────────────────────────────
        section("Crafting")
        btn("🔮  Foulborn Upgrades",                 self.launch_foulborn)
        btn("🧪  Wombgift Evaluator  (Chitinous)",   self.launch_wombgift)
        btn("🧿  Essence Upgrade Paths",              self.launch_essences)

        # ── Mapping & Content ─────────────────────────────────────────────────
        section("Mapping & Content")
        btn("🕷️  Scarab Aggregator  (Bulk Sets)",    self.launch_scarabs)
        btn("🕷️  Scarab Tier Analysis  (Per-Family)", self.launch_scarab_tiers)
        btn("👹  Breachstone Upgrades",              self.launch_breachstone)
        btn("📦  Bulk Fragment Finder",               self.launch_bulk_fragments)
        btn("🌀  Delirium Orb Profits",              self.launch_delirium_orbs)
        btn("🗺️  Expedition Logbook Yields",         self.launch_logbooks)

        # ── Config (fixed at bottom) ─────────────────────────────────────────
        ctk.CTkButton(
            self,
            text="⚙️  Edit Config",
            font=ctk.CTkFont(size=13),
            fg_color="transparent",
            border_width=1,
            border_color="#555555",
            hover_color="#2b2b2b",
            height=32,
            command=self.open_config,
        ).pack(pady=(2, 12), padx=60, fill="x")

    # ── Command runner ───────────────────────────────────────────────────────

    def _run(self, *args: str):
        """Launch main.py with the given args in a persistent terminal window."""
        py = sys.executable
        if os.name == "nt" and py.lower().endswith("pythonw.exe"):
            py = py[:-11] + "python.exe"
        cmd_parts = [py, "main.py"] + list(args)
        if os.name == "nt":
            quoted = " ".join(f'"{p}"' if " " in p else p for p in cmd_parts)
            subprocess.Popen(f'start "POEStick" cmd /k {quoted}', shell=True)
        else:
            subprocess.Popen(cmd_parts)

    # ── Primary ──────────────────────────────────────────────────────────────

    def launch_live_scanner(self):   self._run()
    def launch_single_scan(self):    self._run("--once")

    # ── 3.28 New ─────────────────────────────────────────────────────────────

    def launch_harvest(self):          self._run("--harvest")
    def launch_strongbox(self):        self._run("--strongbox")
    def launch_fossils(self):          self._run("--fossils")
    def launch_astrolabes(self):       self._run("--astrolabes")
    def launch_breach_fortress(self):  self._run("--breach-fortress")

    # ── Market Arbitrage ─────────────────────────────────────────────────────

    def launch_supply_shock(self):    self._run("--supply-shock")
    def launch_div_cards(self):       self._run("--div-cards")
    def launch_gem_arbitrage(self):   self._run("--gem-arbitrage")
    def launch_stacked_deck(self):    self._run("--stacked-deck")
    def launch_gold_squeeze(self):    self._run("--gold-squeeze")

    # ── Crafting ─────────────────────────────────────────────────────────────

    def launch_foulborn(self):        self._run("--foulborn")
    def launch_wombgift(self):        self._run("--wombgift")
    def launch_essences(self):        self._run("--essences")

    # ── Mapping & Content ─────────────────────────────────────────────────────

    def launch_scarabs(self):         self._run("--scarabs")
    def launch_scarab_tiers(self):    self._run("--scarab-tiers")
    def launch_breachstone(self):     self._run("--breachstone")
    def launch_bulk_fragments(self):  self._run("--bulk-fragments")
    def launch_delirium_orbs(self):   self._run("--delirium-orbs")
    def launch_logbooks(self):        self._run("--logbooks")

    # ── Config editor ────────────────────────────────────────────────────────

    def open_config(self):
        import toml

        config_path = "config.toml"
        try:
            config_data = toml.load(config_path)
        except Exception as e:
            print(f"Error loading config.toml: {e}")
            config_data = {}

        win = ctk.CTkToplevel(self)
        win.title("POEStick Settings")
        win.geometry("520x660")
        win.grab_set()

        scroll_frame = ctk.CTkScrollableFrame(win)
        scroll_frame.pack(expand=True, fill="both", padx=10, pady=10)

        self.vars = {}

        for section, params in config_data.items():
            ctk.CTkLabel(
                scroll_frame,
                text=f"— {section.upper()} —",
                font=ctk.CTkFont(weight="bold"),
            ).pack(pady=(14, 4))

            for key, value in params.items():
                row = ctk.CTkFrame(scroll_frame)
                row.pack(fill="x", pady=2, padx=5)

                ctk.CTkLabel(row, text=str(key), width=160, anchor="w").pack(side="left", padx=6)

                if isinstance(value, bool):
                    var = ctk.BooleanVar(value=value)
                    ctk.CTkSwitch(row, text="", variable=var).pack(side="right", padx=6)
                elif isinstance(value, int):
                    var = ctk.IntVar(value=value)
                    ctk.CTkEntry(row, textvariable=var, width=110).pack(side="right", padx=6)
                elif isinstance(value, float):
                    var = ctk.DoubleVar(value=value)
                    ctk.CTkEntry(row, textvariable=var, width=110).pack(side="right", padx=6)
                elif isinstance(value, list):
                    var = ctk.StringVar(value=", ".join(str(v) for v in value))
                    ctk.CTkEntry(row, textvariable=var, width=220).pack(side="right", padx=6)
                else:
                    var = ctk.StringVar(value=str(value))
                    ctk.CTkEntry(row, textvariable=var, width=160).pack(side="right", padx=6)

                self.vars[(section, key)] = (var, type(value))

        def save():
            for (sec, key), (var, orig_type) in self.vars.items():
                val = var.get()
                if orig_type is list:
                    config_data[sec][key] = [v.strip() for v in val.split(",")] if val.strip() else []
                else:
                    config_data[sec][key] = val
            with open(config_path, "w") as f:
                toml.dump(config_data, f)
            win.destroy()

        ctk.CTkButton(
            win, text="Save Settings", command=save,
            fg_color="#1a5c2a", hover_color="#2a7a3a",
        ).pack(pady=10)


if __name__ == "__main__":
    app = POEStickLauncher()
    app.mainloop()
