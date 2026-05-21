import tkinter as tk
from tkinter import ttk, messagebox
from picosdk.ps3000a import ps3000a as ps
import pyvisa
import time
import ctypes
import numpy as np
import pandas as pd # NOTE: Requires 'openpyxl' for Excel export (pip install openpyxl)
import os
import time as time_module
from datetime import datetime

# ------------------------------
# VISA SETUP (WAVEFORM GENERATOR)
# ------------------------------
rm = pyvisa.ResourceManager()
visa_address = 'USB0::0x2A8D::0x8D01::CN62210142::0::INSTR'

# Global reference for the generator
try:
    waveform_generator = rm.open_resource(visa_address)
except:
    print("⚠️ Warning: Could not connect to Waveform Generator. Check USB/Address.")

def protocol_builder(type, Duration, ipg, resolution, a):
    protocol = '0'
    if type == "Biphasic Cathodic":
        protocol += ', -1' * Duration
        protocol += ', 0' * ipg
        # Using an f-string to inject the value of 1*a, and int() to avoid float multiplication errors
        protocol += f', {1*a}' * int(Duration/a)
        # Adjusted the remaining zeros formula to account for the new asymmetric length
        protocol += ', 0' * int(resolution - ipg - Duration - (Duration/a) - 1)
    elif type == "Biphasic Anodic":
        protocol += ', 1' * Duration
        protocol += ', 0' * ipg
        protocol += ', -1' * Duration
        protocol += ', 0' * (resolution - ipg - Duration * 2 - 1)
    elif type == "Anodic":
        protocol += ', 1' * Duration
        protocol += ', 0' * (resolution - Duration - 1)
    elif type == "Cathodic":
        protocol += ', -1' * Duration
        protocol += ', 0' * (resolution - Duration - 1)
    return protocol

# ------------------------------
# EXPERIMENT RUNNER (AWG)
# ------------------------------
def run_waveform(stim_type, Duration, ipg, amplitude1, a):
    resolution = 1000
    stim = protocol_builder(stim_type, Duration, ipg, resolution, a)
    waveform_generator.write("*RST")
    time.sleep(0.5)
    waveform_generator.write('OUTP1 OFF')
    waveform_generator.write('OUTP2 OFF')
    sample_rate1 = 1_000_000
    frequency = 11
    period = 1 / frequency
    waveform_generator.write(''.join(['DATA:ARB STIM,', stim]))
    waveform_generator.write('FUNC:ARB STIM')
    waveform_generator.write('FUNC ARB')
    waveform_generator.write(f'FUNC:ARB:SRATE {sample_rate1:.3f}')
    waveform_generator.write("BURS:STATE ON")
    waveform_generator.write("BURS:MODE TRIG")
    waveform_generator.write("BURS:NCYC 1")
    waveform_generator.write("BURS:PHAS 0")
    waveform_generator.write(f"VOLT {amplitude1:.3f}")
    waveform_generator.write(f"BURS:INT:PER {period}")

    # shorting channel
    short = '0'
    short += ', 0' * 299
    short += ', 1' * 450
    sample_rate2 = 750 / period
    amplitude2 = 2.5
    waveform_generator.write(''.join(['SOURCE2:DATA:ARB SHORT,', short]))
    waveform_generator.write('SOURCE2:FUNC:ARB SHORT')
    waveform_generator.write('SOURCE2:FUNC ARB')
    waveform_generator.write(f'SOURCE2:FUNC:ARB:SRATE {sample_rate2:.3f}')
    waveform_generator.write("SOURCE2:BURS:STATE ON")
    waveform_generator.write("SOURCE2:BURS:MODE TRIG")
    waveform_generator.write("SOURCE2:BURS:NCYC 1")
    waveform_generator.write("SOURCE2:BURS:PHASe 60")
    waveform_generator.write(f"SOURCE2:VOLT {amplitude2:.3f}")
    waveform_generator.write(f"SOURCE2:BURS:INT:PER {period}")
    waveform_generator.write("FUNC:ARB:SYNC")
    waveform_generator.write("OUTP1 ON")
    waveform_generator.write("OUTP2 ON")

# ==============================
# PICO SCOPE SETUP & CAPTURE
# ==============================
PICO_SAVE_DIR = r"C:\Users\uzivatel\Desktop\lukas_protokoly\picoSDK_capture"
LOG_DIR = r"C:\Users\uzivatel\Desktop\lukas_protokoly\run_log"
enabled_channels = ['A', 'B', 'C']
PICO_RANGES_V = {
    0: 0.01, 1: 0.02, 2: 0.05, 3: 0.1, 4: 0.2,
    5: 0.5, 6: 1.0, 7: 2.0, 8: 5.0, 9: 10.0, 10: 20.0
}
current_channel_ranges = {ch: 10 for ch in enabled_channels}
pre_trigger, post_trigger = 1000, 23000
total_samples = pre_trigger + post_trigger
timebase, oversample, segment_index, decimation_factor = 8, 0, 0, 1
trigger_channel = ps.PS3000A_CHANNEL['PS3000A_EXTERNAL']
trigger_threshold_mv, trigger_direction = 1000, ps.PS3000A_THRESHOLD_DIRECTION['PS3000A_RISING']

os.makedirs(PICO_SAVE_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)
pico_handle = ctypes.c_int16()
time_interval_ns = ctypes.c_float()
max_samples = ctypes.c_int32()
pico_initialized = False

def init_pico():
    global pico_initialized, pico_handle
    if pico_initialized: return
    status = ps.ps3000aOpenUnit(ctypes.byref(pico_handle), None)
    if status != 0: raise OSError(f"Pico Error: {status}")
    for ch in ['A', 'B', 'C', 'D']:
        if ch in enabled_channels:
            ps.ps3000aSetChannel(pico_handle, ps.PS3000A_CHANNEL[f'PS3000A_CHANNEL_{ch}'], 1, 1, current_channel_ranges[ch], 0)
        else:
            ps.ps3000aSetChannel(pico_handle, ps.PS3000A_CHANNEL[f'PS3000A_CHANNEL_{ch}'], 0, 1, 10, 0)
    ps.ps3000aSetSimpleTrigger(pico_handle, 1, trigger_channel, trigger_threshold_mv, trigger_direction, 0, 0)
    ps.ps3000aGetTimebase2(pico_handle, timebase, total_samples, ctypes.byref(time_interval_ns), 0, ctypes.byref(max_samples), 0)
    pico_initialized = True

def pico_capture():
    time_indisposed = ctypes.c_int32()
    for ch in enabled_channels:
        current_channel_ranges[ch] = 9 # Reset to 10V range for dummy capture
        ps.ps3000aSetChannel(pico_handle, ps.PS3000A_CHANNEL[f'PS3000A_CHANNEL_{ch}'], 1, 1, 9, 0)
    ps.ps3000aRunBlock(pico_handle, pre_trigger, post_trigger, timebase, oversample, ctypes.byref(time_indisposed), 0, None, None)
    ready = ctypes.c_int16(0)
    while not ready.value:
        ps.ps3000aIsReady(pico_handle, ctypes.byref(ready))
        time_module.sleep(0.001)

    dummy_buffers = {}
    for ch in enabled_channels:
        dummy_buffers[ch] = (ctypes.c_int16 * total_samples)()
        ps.ps3000aSetDataBuffer(pico_handle, ps.PS3000A_CHANNEL[f'PS3000A_CHANNEL_{ch}'], ctypes.byref(dummy_buffers[ch]), total_samples, 0, 0)
    ps.ps3000aGetValues(pico_handle, 0, ctypes.byref(ctypes.c_int32(total_samples)), 1, 0, 0, None)
    ps.ps3000aStop(pico_handle)

    print("--- Auto-Ranging Results ---")
    for ch in enabled_channels:
        dummy_data = np.array(dummy_buffers[ch])
        # 3. Use the 99.5th percentile instead of max() to ignore microsecond noise spikes
        max_adc = np.percentile(np.abs(dummy_data), 99)
        max_voltage = max_adc * (PICO_RANGES_V[9] / 32767.0)
        target_voltage = max_voltage * 1.05
        optimal_range = 10
        for r_idx in sorted(PICO_RANGES_V.keys()):
            if PICO_RANGES_V[r_idx] >= target_voltage:
                optimal_range = r_idx
                break
        current_channel_ranges[ch] = optimal_range
        ps.ps3000aSetChannel(pico_handle, ps.PS3000A_CHANNEL[f'PS3000A_CHANNEL_{ch}'], 1, 1, optimal_range, 0)
        print(f"Ch {ch}: Max V = {max_voltage:.4f}V | Target = {target_voltage:.4f}V | Chosen Range = {PICO_RANGES_V[optimal_range]}V")
    print("----------------------------")

    ps.ps3000aRunBlock(pico_handle, pre_trigger, post_trigger, timebase, oversample, ctypes.byref(time_indisposed), 0, None, None)
    ready = ctypes.c_int16(0)
    while not ready.value:
        ps.ps3000aIsReady(pico_handle, ctypes.byref(ready))
        time_module.sleep(0.001)

    real_buffers = {}
    for ch in enabled_channels:
        real_buffers[ch] = (ctypes.c_int16 * total_samples)()
        ps.ps3000aSetDataBuffer(pico_handle, ps.PS3000A_CHANNEL[f'PS3000A_CHANNEL_{ch}'], ctypes.byref(real_buffers[ch]), total_samples, 0, 0)
    ps.ps3000aGetValues(pico_handle, 0, ctypes.byref(ctypes.c_int32(total_samples)), 1, 0, 0, None)

    data_dict = {"Time (us)": (np.arange(total_samples) - pre_trigger) * time_interval_ns.value / 1000}
    for ch in enabled_channels:
        ch_scale = PICO_RANGES_V[current_channel_ranges[ch]] / 32767.0
        data_dict[f"Ch{ch}"] = np.array(real_buffers[ch]) * ch_scale
    ps.ps3000aStop(pico_handle)
    return data_dict

def close_pico():
    global pico_initialized
    if pico_initialized:
        ps.ps3000aCloseUnit(pico_handle)
        pico_initialized = False

def log_iteration(log_path, start_time, iter_idx, r_idx, stim_type, dur, ipg, amp, param, val):
    with open(log_path, "a") as f:
        f.write(f"Global: {iter_idx} | Repeat: {r_idx} | Time: {start_time} | Type: {stim_type} | Dur: {dur} | IPG: {ipg} | Amp: {amp:.4f} | Param: {param}={val}\n")

# ------------------------------
# LOOP LOGIC
# ------------------------------
def start_loop():
    try:
        base_type = type_var.get()
        base_dur = int(Duration_entry.get())
        base_ipg = int(ipg_entry.get())
        base_amp = float(amplitude_entry.get())
        base_a = float(asym_entry.get())  # Get asymmetricity from UI
        n_repeats = int(n_var.get())
        on_t, off_t = float(on_time_entry.get()), float(off_time_entry.get())
        is_sweeping = sweep_enabled.get()
        is_locked = lock_charge_var.get()
        chosen = param_var.get()

        # Calculate Base Product for the aspect ratio lock
        base_target_charge = base_dur * base_amp

        if is_sweeping:
            param_range = np.arange(float(min_entry.get()), float(max_entry.get()) + (float(step_entry.get())/10), float(step_entry.get()))
        else:
            param_range = [0.0]

        total_steps = len(param_range) * n_repeats
        total_time_est = total_steps * (on_t + off_t)

        confirm = tk.Toplevel(root)
        confirm.title("Confirm Run")
        mode_text = f"Parameter Sweep ({chosen})" if is_sweeping else "Static Repeat"

        # Add visual confirmation that lock is active
        lock_status = "\n[Charge Lock Enabled: Amp/Dur will adapt dynamically]" if is_locked and chosen in ["Duration", "Amplitude"] else ""

        ttk.Label(
            confirm,
            text=(
                f"Mode: {mode_text}{lock_status}\n"
                f"Unique Parameter Steps: {len(param_range)}\n"
                f"Repeats per step: {n_repeats}\n"
                f"Total Iterations: {total_steps}\n\n"
                f"Estimated Duration: {total_time_est/60:.1f} minutes"
            ),
            font=("Arial", 10, "bold"),
            justify="center"
        ).pack(padx=30, pady=20)

        def run_now():
            confirm.destroy()
            try:
                init_pico()
            except Exception as e:
                messagebox.showerror("PicoScope Error", str(e))
                return

            log_path = os.path.join(LOG_DIR, f"Log_{datetime.now().strftime('%Y%m%d_%H%M')}.txt")
            excel_filename = os.path.join(PICO_SAVE_DIR, f"CaptureData_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx")
            global_idx = 0

            # Initialize dictionary of DataFrames for Excel accumulation
            channel_dfs = {ch: pd.DataFrame() for ch in enabled_channels}
            time_initialized = False

            for p_val in param_range:
                curr_type, curr_dur, curr_ipg, curr_amp, curr_a = base_type, base_dur, base_ipg, base_amp, base_a

                if is_sweeping:
                    if chosen == "Duration":
                        curr_dur = int(p_val)
                        if is_locked and curr_dur != 0:
                            curr_amp = base_target_charge / curr_dur
                    elif chosen == "IPG":
                        curr_ipg = int(p_val)
                    elif chosen == "Amplitude":
                        curr_amp = p_val
                        if is_locked and curr_amp != 0:
                            curr_dur = int(base_target_charge / curr_amp)
                    elif chosen == "Type":
                        types = ["Biphasic Cathodic", "Biphasic Anodic", "Anodic", "Cathodic"]
                        curr_type = types[int(p_val)%4]

                for r_idx in range(n_repeats):
                    start_t = datetime.now()
                    print(f"Executing: Step {p_val:.3f} | Repeat {r_idx+1}/{n_repeats} | Dur={curr_dur}, Amp={curr_amp:.4f}")

                    # Run Waveform Output
                    run_waveform(curr_type, curr_dur, curr_ipg, curr_amp, curr_a)

                    # Capture ONLY ONCE per setting step (during first repeat)
                    if r_idx == 0:
                        time.sleep(on_t / 2)
                        try:
                            cap_data = pico_capture()
                            col_name = f"{chosen}_{p_val:.2f}" if is_sweeping else f"Setting_{global_idx}"
                            # Add Time index column once
                            if not time_initialized:
                                for ch in enabled_channels:
                                    channel_dfs[ch]["Time (us)"] = cap_data["Time (us)"]
                                time_initialized = True
                            # Append new iteration as a new column to each respective channel sheet
                            for ch in enabled_channels:
                                channel_dfs[ch][col_name] = cap_data[f"Ch{ch}"]
                        except Exception as e:
                            print(f"Capture failed at iteration {global_idx}: {e}")
                        time.sleep(on_t / 2)
                    else:
                        # Skip capture overhead, just wait out the cycle
                        time.sleep(on_t)

                    waveform_generator.write("OUTP1 OFF")
                    waveform_generator.write("SOURCE2:FUNC DC")
                    waveform_generator.write("SOURCE2:VOLT:OFFSET 2.5")
                    waveform_generator.write("OUTP2 ON")
                    time.sleep(off_t)
                    waveform_generator.write("OUTP2 OFF")
                    waveform_generator.write("SOURCE2:VOLT:OFFSET 0.0")
                    waveform_generator.write("SOURCE2:FUNC ARB")
                    log_iteration(log_path, start_t, global_idx, r_idx, curr_type, curr_dur, curr_ipg, curr_amp, chosen, p_val)
                    global_idx += 1

            close_pico()

            # --- Save accummulated DataFrames to Excel Workbook ---
            try:
                print("Exporting data to Excel...")
                with pd.ExcelWriter(excel_filename, engine='openpyxl') as writer:
                    for ch in enabled_channels:
                        # Write each channel to its own designated sheet
                        channel_dfs[ch].to_excel(writer, sheet_name=f'Channel_{ch}', index=False)
                print(f"Excel export complete: {excel_filename}")
                messagebox.showinfo("Complete", "The experiment sequence has finished and data was saved to Excel.")
            except Exception as e:
                messagebox.showerror("Export Error", f"Failed to save Excel file. (Did you pip install openpyxl?)\nError: {e}")

        btn_frame = ttk.Frame(confirm)
        btn_frame.pack(pady=10)
        ttk.Button(btn_frame, text="Start Experiment", command=run_now).pack(side="left", padx=10)
        ttk.Button(btn_frame, text="Cancel", command=confirm.destroy).pack(side="right", padx=10)

    except Exception as e:
        messagebox.showerror("Error", f"Invalid input values: {e}")

# ------------------------------
# GUI SETUP
# ------------------------------
root = tk.Tk()
root.title("Stimulator Control GUI v2.1")

sweep_enabled = tk.BooleanVar(value=False)
tk.Checkbutton(root, text="Enable Parameter Sweep", variable=sweep_enabled, font=("Arial", 10)).grid(row=0, column=0, columnspan=2, pady=10)

tk.Label(root, text="Type:").grid(row=1, column=0, sticky="w")
type_var = tk.StringVar(value="Biphasic Cathodic")
ttk.Combobox(root, textvariable=type_var, values=["Biphasic Cathodic", "Biphasic Anodic", "Anodic", "Cathodic"], state="readonly").grid(row=1, column=1)

tk.Label(root, text="Base Duration:").grid(row=2, column=0, sticky="w")
Duration_entry = tk.Entry(root); Duration_entry.insert(0, "250"); Duration_entry.grid(row=2, column=1)

tk.Label(root, text="Base IPG:").grid(row=3, column=0, sticky="w")
ipg_entry = tk.Entry(root); ipg_entry.insert(0, "50"); ipg_entry.grid(row=3, column=1)

tk.Label(root, text="Base Amplitude (V):").grid(row=4, column=0, sticky="w")
amplitude_entry = tk.Entry(root); amplitude_entry.insert(0, "0.235"); amplitude_entry.grid(row=4, column=1)

tk.Label(root, text="Asymmetricity (a):").grid(row=5, column=0, sticky="w")
asym_entry = tk.Entry(root); asym_entry.insert(0, "1.0"); asym_entry.grid(row=5, column=1)

tk.Label(root, text="N Repeats (per setting):", fg="blue").grid(row=6, column=0, sticky="w")
n_var = tk.StringVar(value="1"); tk.Entry(root, textvariable=n_var).grid(row=6, column=1)

tk.Label(root, text="Sweep Parameter:").grid(row=7, column=0, sticky="w")
param_var = tk.StringVar(value="Amplitude")
ttk.Combobox(root, textvariable=param_var, values=["Duration", "IPG", "Amplitude", "Type"], state="readonly").grid(row=7, column=1)

# ----- NEW CHARGE LOCK CHECKBOX -----
lock_charge_var = tk.BooleanVar(value=False)
tk.Checkbutton(root, text="Charge lock", variable=lock_charge_var, fg="red").grid(row=7, column=2, sticky="w", padx=10)
# ------------------------------------

tk.Label(root, text="Sweep (Min/Max/Step):").grid(row=8, column=0, sticky="w")
range_frame = tk.Frame(root)
range_frame.grid(row=8, column=1)
min_entry = tk.Entry(range_frame, width=6); min_entry.insert(0, "0.1"); min_entry.pack(side="left")
max_entry = tk.Entry(range_frame, width=6); max_entry.insert(0, "0.5"); max_entry.pack(side="left")
step_entry = tk.Entry(range_frame, width=6); step_entry.insert(0, "0.1"); step_entry.pack(side="left")

tk.Label(root, text="Stim / Diffuse Time (s):").grid(row=9, column=0, sticky="w")
time_frame = tk.Frame(root)
time_frame.grid(row=9, column=1)
on_time_entry = tk.Entry(time_frame, width=9); on_time_entry.insert(0, "300"); on_time_entry.pack(side="left")
off_time_entry = tk.Entry(time_frame, width=9); off_time_entry.insert(0, "600"); off_time_entry.pack(side="left")

tk.Button(root, text="RUN", command=start_loop, bg="#27ae60", fg="white", font=("Arial", 11, "bold")).grid(row=10, column=0, columnspan=2, pady=20)

root.mainloop()