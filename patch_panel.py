#!/usr/bin/env python3
"""
Audio Patch Panel for Linux Mint (PulseAudio/PipeWire)
Author: Desktop Computer Programmer
Version: 4.1 (State Persistence & Selection UX Patch)
"""

import sys
import os
import json
import subprocess
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QListWidget, QPushButton, QLabel, 
                             QMessageBox, QListWidgetItem, QSlider, QInputDialog)
from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QFont

CONFIG_PATH = os.path.expanduser("~/.config/mint_audio_patch_panel.json")

class StateManager:
    """Handles persistent storage of routing rules."""
    @staticmethod
    def load():
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, 'r') as f:
                    return json.load(f)
            except json.JSONDecodeError:
                return {}
        return {}

    @staticmethod
    def save(config_dict):
        try:
            with open(CONFIG_PATH, 'w') as f:
                json.dump(config_dict, f, indent=4)
            return True
        except Exception as e:
            print(f"Failed to save config: {e}")
            return False

class AudioBackend:
    """Handles all subprocess calls to the PulseAudio/PipeWire subsystem."""
    @staticmethod
    def get_sinks():
        try:
            result = subprocess.run(['pactl', '-f', 'json', 'list', 'sinks'], 
                                    capture_output=True, text=True, check=True)
            return json.loads(result.stdout)
        except Exception:
            return []

    @staticmethod
    def get_sink_inputs():
        try:
            result = subprocess.run(['pactl', '-f', 'json', 'list', 'sink-inputs'], 
                                    capture_output=True, text=True, check=True)
            return json.loads(result.stdout)
        except Exception:
            return []

    @staticmethod
    def move_stream(stream_index, sink_name):
        try:
            subprocess.run(['pactl', 'move-sink-input', str(stream_index), str(sink_name)], check=True)
            return True
        except subprocess.CalledProcessError:
            return False

    @staticmethod
    def set_stream_volume(stream_index, vol_percent):
        try:
            subprocess.run(['pactl', 'set-sink-input-volume', str(stream_index), f'{vol_percent}%'], check=True)
        except subprocess.CalledProcessError:
            pass

    @staticmethod
    def set_sink_volume(sink_name, vol_percent):
        try:
            subprocess.run(['pactl', 'set-sink-volume', str(sink_name), f'{vol_percent}%'], check=True)
        except subprocess.CalledProcessError:
            pass

    @staticmethod
    def create_virtual_sink(description):
        safe_name = description.replace(" ", "_").replace("-", "_")
        try:
            subprocess.run([
                'pactl', 'load-module', 'module-null-sink', 
                f'sink_name=Virtual_{safe_name}', 
                f'sink_properties=device.description={safe_name}'
            ], check=True)
            return True
        except subprocess.CalledProcessError as e:
            print(f"Failed to create virtual sink: {e}")
            return False

    @staticmethod
    def destroy_module(module_id):
        try:
            subprocess.run(['pactl', 'unload-module', str(module_id)], check=True)
            return True
        except subprocess.CalledProcessError as e:
            print(f"Failed to destroy virtual sink: {e}")
            return False


class PatchPanelWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Mint Audio Patch Panel v4.1 (Final)")
        self.setGeometry(100, 100, 750, 550)
        
        self.current_streams = []
        self.current_sinks = []
        self.known_stream_ids = set() 
        self._updating_ui = False
        
        self.init_ui()
        self.refresh_audio_data()
        
        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self.refresh_audio_data)
        self.poll_timer.start(2000)

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        lists_layout = QHBoxLayout()
        
        # --- Left Panel: Streams ---
        stream_layout = QVBoxLayout()
        stream_label = QLabel("Active Audio Streams (Apps):")
        stream_label.setFont(QFont("Arial", 10, QFont.Bold))
        self.stream_list = QListWidget()
        self.stream_list.itemSelectionChanged.connect(self.on_stream_selected)
        
        self.stream_vol_label = QLabel("App Volume: 100%")
        self.stream_vol_slider = QSlider(Qt.Horizontal)
        self.stream_vol_slider.setRange(0, 150) 
        self.stream_vol_slider.setValue(100)
        self.stream_vol_slider.setEnabled(False)
        self.stream_vol_slider.valueChanged.connect(self.change_stream_volume)
        
        stream_layout.addWidget(stream_label)
        stream_layout.addWidget(self.stream_list)
        stream_layout.addWidget(self.stream_vol_label)
        stream_layout.addWidget(self.stream_vol_slider)
        
        # --- Right Panel: Hardware & Virtual Sinks ---
        sink_layout = QVBoxLayout()
        sink_label = QLabel("Output Devices & Virtual Cables:")
        sink_label.setFont(QFont("Arial", 10, QFont.Bold))
        self.sink_list = QListWidget()
        self.sink_list.itemSelectionChanged.connect(self.on_sink_selected)
        
        virtual_btn_layout = QHBoxLayout()
        self.create_cable_btn = QPushButton("➕ Add Virtual Cable")
        self.create_cable_btn.clicked.connect(self.create_virtual_cable)
        self.remove_cable_btn = QPushButton("➖ Remove Selected")
        self.remove_cable_btn.clicked.connect(self.remove_virtual_cable)
        virtual_btn_layout.addWidget(self.create_cable_btn)
        virtual_btn_layout.addWidget(self.remove_cable_btn)
        
        self.sink_vol_label = QLabel("Master Volume: 100%")
        self.sink_vol_slider = QSlider(Qt.Horizontal)
        self.sink_vol_slider.setRange(0, 150)
        self.sink_vol_slider.setValue(100)
        self.sink_vol_slider.setEnabled(False)
        self.sink_vol_slider.valueChanged.connect(self.change_sink_volume)
        
        sink_layout.addWidget(sink_label)
        sink_layout.addWidget(self.sink_list)
        sink_layout.addLayout(virtual_btn_layout)
        sink_layout.addWidget(self.sink_vol_label)
        sink_layout.addWidget(self.sink_vol_slider)
        
        lists_layout.addLayout(stream_layout)
        lists_layout.addLayout(sink_layout)
        
        # --- Action Buttons ---
        action_layout = QHBoxLayout()
        
        self.patch_btn = QPushButton("🔗 Patch Stream Once")
        self.patch_btn.setMinimumHeight(45)
        self.patch_btn.setFont(QFont("Arial", 10, QFont.Bold))
        self.patch_btn.clicked.connect(self.execute_patch)
        
        self.save_default_btn = QPushButton("💾 Save Route as Default")
        self.save_default_btn.setMinimumHeight(45)
        self.save_default_btn.setFont(QFont("Arial", 10, QFont.Bold))
        self.save_default_btn.clicked.connect(self.save_default_route)
        
        action_layout.addWidget(self.patch_btn)
        action_layout.addWidget(self.save_default_btn)
        
        main_layout.addLayout(lists_layout)
        main_layout.addLayout(action_layout)

    def _extract_volume(self, volume_dict):
        if not volume_dict: return 100
        try:
            first_channel = list(volume_dict.values())[0]
            return int(first_channel.get('value_percent', '100%').strip('%'))
        except (KeyError, IndexError, ValueError):
            return 100

    def refresh_audio_data(self):
        streams = AudioBackend.get_sink_inputs()
        sinks = AudioBackend.get_sinks()
        
        # Auto-Routing Logic
        active_indexes = {s.get('index') for s in streams}
        new_indexes = active_indexes - self.known_stream_ids
        
        if new_indexes:
            config = StateManager.load()
            available_sinks = [sink.get('name') for sink in sinks]
            auto_routed = False
            
            for stream in streams:
                idx = stream.get('index')
                if idx in new_indexes:
                    app_name = stream.get('properties', {}).get('application.name')
                    if app_name and app_name in config:
                        target_sink = config[app_name]
                        if target_sink in available_sinks:
                            if AudioBackend.move_stream(idx, target_sink):
                                auto_routed = True
                                
            if auto_routed:
                streams = AudioBackend.get_sink_inputs()
                
        self.known_stream_ids = {s.get('index') for s in streams}
        
        # UI Refresh Logic - Safely storing current items
        current_stream_items = self.stream_list.selectedItems()
        selected_stream_idx = current_stream_items[0].data(Qt.UserRole) if current_stream_items else None
        
        current_sink_items = self.sink_list.selectedItems()
        selected_sink_name = current_sink_items[0].data(Qt.UserRole) if current_sink_items else None

        if streams != self.current_streams:
            self.current_streams = streams
            self.stream_list.clear()
            for stream in streams:
                app_name = stream.get('properties', {}).get('application.name', 'Unknown Stream')
                idx = stream.get('index')
                vol = self._extract_volume(stream.get('volume'))
                
                item = QListWidgetItem(f"[{idx}] {app_name}")
                item.setData(Qt.UserRole, idx)
                item.setData(Qt.UserRole + 1, vol) 
                item.setData(Qt.UserRole + 4, app_name) 
                self.stream_list.addItem(item)
                
                # BUGFIX: Hard-reset the current item to prevent selection loss
                if idx == selected_stream_idx:
                    item.setSelected(True)
                    self.stream_list.setCurrentItem(item)
                
        if sinks != self.current_sinks:
            self.current_sinks = sinks
            self.sink_list.clear()
            for sink in sinks:
                desc = sink.get('properties', {}).get('device.description', sink.get('name'))
                idx = sink.get('index')
                vol = self._extract_volume(sink.get('volume'))
                owner_mod = sink.get('owner_module')
                driver = sink.get('driver', '')
                
                if "module-null-sink" in driver:
                    clean_desc = desc.replace("_", " ").replace("Virtual ", "")
                    display_text = f"[VIRTUAL] {clean_desc}"
                else:
                    display_text = f"[{idx}] {desc}"
                
                item = QListWidgetItem(display_text)
                item.setData(Qt.UserRole, sink.get('name'))
                item.setData(Qt.UserRole + 1, vol) 
                item.setData(Qt.UserRole + 2, owner_mod)
                item.setData(Qt.UserRole + 3, driver)
                self.sink_list.addItem(item)
                
                # BUGFIX: Hard-reset the current item to prevent selection loss
                if sink.get('name') == selected_sink_name:
                    item.setSelected(True)
                    self.sink_list.setCurrentItem(item)

    def on_stream_selected(self):
        items = self.stream_list.selectedItems()
        if items:
            self._updating_ui = True
            vol = items[0].data(Qt.UserRole + 1)
            self.stream_vol_slider.setEnabled(True)
            self.stream_vol_slider.setValue(vol)
            self.stream_vol_label.setText(f"App Volume: {vol}%")
            self._updating_ui = False

    def on_sink_selected(self):
        items = self.sink_list.selectedItems()
        if items:
            self._updating_ui = True
            vol = items[0].data(Qt.UserRole + 1)
            self.sink_vol_slider.setEnabled(True)
            self.sink_vol_slider.setValue(vol)
            self.sink_vol_label.setText(f"Master Volume: {vol}%")
            self._updating_ui = False

    def change_stream_volume(self, value):
        if self._updating_ui: return
        self.stream_vol_label.setText(f"App Volume: {value}%")
        items = self.stream_list.selectedItems()
        if items:
            stream_idx = items[0].data(Qt.UserRole)
            items[0].setData(Qt.UserRole + 1, value)
            AudioBackend.set_stream_volume(stream_idx, value)

    def change_sink_volume(self, value):
        if self._updating_ui: return
        self.sink_vol_label.setText(f"Master Volume: {value}%")
        items = self.sink_list.selectedItems()
        if items:
            sink_name = items[0].data(Qt.UserRole)
            items[0].setData(Qt.UserRole + 1, value) 
            AudioBackend.set_sink_volume(sink_name, value)

    def create_virtual_cable(self):
        text, ok = QInputDialog.getText(self, 'Create Virtual Cable', 
                                        'Enter a friendly name for this cable (e.g., OBS Audio):')
        if ok and text:
            if AudioBackend.create_virtual_sink(text):
                self.refresh_audio_data() 

    def remove_virtual_cable(self):
        # BUGFIX: Use selectedItems() instead of currentItem()
        items = self.sink_list.selectedItems()
        if not items:
            QMessageBox.warning(self, "Selection Error", "Please select a virtual cable to remove.")
            return
            
        driver = items[0].data(Qt.UserRole + 3)
        if "module-null-sink" not in driver:
            QMessageBox.critical(self, "Protected Hardware", 
                                 "You cannot remove physical hardware output devices from the patch panel.")
            return
            
        module_id = items[0].data(Qt.UserRole + 2)
        if module_id is not None:
            if AudioBackend.destroy_module(module_id):
                self.refresh_audio_data()

    def execute_patch(self):
        # BUGFIX: Rely strictly on highlighted selectedItems() 
        selected_streams = self.stream_list.selectedItems()
        selected_sinks = self.sink_list.selectedItems()
        
        if not selected_streams or not selected_sinks:
            QMessageBox.warning(self, "Selection Error", "Please select both a stream and an output device.")
            return
            
        stream_idx = selected_streams[0].data(Qt.UserRole)
        sink_name = selected_sinks[0].data(Qt.UserRole)
        
        if AudioBackend.move_stream(stream_idx, sink_name):
            self.statusBar().showMessage(f"Successfully patched stream to {sink_name}", 3000)
            self.refresh_audio_data()
        else:
            QMessageBox.critical(self, "Routing Error", "Failed to route the audio stream.")

    def save_default_route(self):
        # BUGFIX: Rely strictly on highlighted selectedItems() 
        selected_streams = self.stream_list.selectedItems()
        selected_sinks = self.sink_list.selectedItems()
        
        if not selected_streams or not selected_sinks:
            QMessageBox.warning(self, "Selection Error", "Please select a stream and the output device you want as its default.")
            return
            
        app_name = selected_streams[0].data(Qt.UserRole + 4)
        sink_name = selected_sinks[0].data(Qt.UserRole)
        
        if not app_name or app_name == "Unknown Stream":
            QMessageBox.warning(self, "Identification Error", "Cannot save default: Application name is unknown to the system.")
            return
            
        stream_idx = selected_streams[0].data(Qt.UserRole)
        AudioBackend.move_stream(stream_idx, sink_name)
            
        config = StateManager.load()
        config[app_name] = sink_name
        
        if StateManager.save(config):
            self.statusBar().showMessage(f"Saved Rule: '{app_name}' will always output to '{sink_name}'", 5000)
            self.refresh_audio_data()
        else:
            QMessageBox.critical(self, "Save Error", "Failed to write configuration file.")

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion") 
    window = PatchPanelWindow()
    window.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()