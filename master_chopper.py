import pandas as pd
import re
import tkinter as tk
from tkinter import filedialog, messagebox

# ==========================================
# HELPER FUNCTIONS
# ==========================================
def parse_log_file(txt_path):
    """Parses the text file to extract Timestamps and Amplitude values."""
    with open(txt_path, 'r', encoding='utf-8') as f:
        content = f.read()
    times = re.findall(r'Time:\s*(\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2}(?:\.\d+)?)', content)
    amps = re.findall(r'Amp:\s*(\d+(?:\.\d+)?)', content)
    events = []
    for t_str, amp_str in zip(times, amps):
        events.append({
            'time': pd.to_datetime(t_str),
            'amp': amp_str
        })
    return events

# ==========================================
# DATA PROCESSING
# ==========================================
def process_measurement_data(input_excel, input_txt, output_excel, apply_baseline, apply_stats):
    """Main function to load Excel, process data, slice segments, and export."""
    events = parse_log_file(input_txt)
    if not events:
        raise ValueError("No valid timestamp/amp events found in the log file.")

    TARGET_SHEET = "Data (1 fx-6 UniAmp (205145))"
    TIME_COL = "Time (YYYY-MM-DD hh:mm:ss)"
    SIGNAL_COLS = [
        "Sensor 1 - H2 (% Sat)",
        "Sensor 2 - OX (% Sat)",
        "Sensor 3 - pH (pH unit)"
    ]

    OFFSETS = {
        "Sensor 1 - H2 (% Sat)": 0,
        "Sensor 2 - OX (% Sat)": 21,
        "Sensor 3 - pH (pH unit)": 7.4
    }
    cols_to_use = [TIME_COL] + SIGNAL_COLS

    df = pd.read_excel(input_excel, sheet_name=TARGET_SHEET, usecols=cols_to_use)
    df[TIME_COL] = pd.to_datetime(df[TIME_COL])
    df = df.set_index(TIME_COL).sort_index()

    extracted_data = {sig: {} for sig in SIGNAL_COLS}
    grand_means_cache = {sig: {"avg": 0, "std": 0} for sig in SIGNAL_COLS}

    for event in events:
        target_time = event['time']
        amp_val = event['amp']
        time_str_header = target_time.strftime('%H-%M-%S')
        col_name = f"Amp_{amp_val}_{time_str_header}"

        nearest_idx = df.index.get_indexer([target_time], method='nearest')[0]
        event_actual_time = df.index[nearest_idx]

        start_time = event_actual_time - pd.Timedelta(minutes=2)
        end_time = event_actual_time + pd.Timedelta(minutes=12)

        segment = df.loc[start_time:end_time]

        for sig in SIGNAL_COLS:
            raw_series = pd.Series(segment[sig].values)
            # Calculate the mean of rows 2-122 for the grand mean later
            # (Excel rows 2-122 = index 0 to 120)
            segment_baseline_avg = raw_series.iloc[:121].mean()
            segment_baseline_std = raw_series.iloc[:121].std()

            if apply_baseline:
                x = segment_baseline_avg
                o = OFFSETS[sig]
                processed_series = o + raw_series - x
                extracted_data[sig][col_name] = processed_series
            else:
                extracted_data[sig][col_name] = raw_series

    with pd.ExcelWriter(output_excel, engine='openpyxl') as writer:
        master_dict = {}
        grand_mean_row = {"Nábojová hustota": "0"}

        for sig in SIGNAL_COLS:
            sig_df = pd.DataFrame(extracted_data[sig])

            # Temporary lists to calculate the final grand mean for this sensor
            all_baseline_avgs = []
            all_baseline_stds = []

            if apply_stats:
                new_df = pd.DataFrame()
                original_cols = sig_df.columns.tolist()
                first_col = original_cols[0] if len(original_cols) > 0 else None

                for i in range(0, len(original_cols), 5):
                    chunk_cols = original_cols[i:i+5]
                    for col in chunk_cols:
                        new_df[col] = sig_df[col]

                    # Track baseline stats for the "Zeroth" row calculation
                    # We look at the raw extracted data for these specific columns
                    for col in chunk_cols:
                        all_baseline_avgs.append(sig_df[col].iloc[0:121].mean())
                        all_baseline_stds.append(sig_df[col].iloc[0:121].std())

                    cols_for_math = [c for c in chunk_cols if c != first_col]
                    chunk_idx = i // 5 + 1
                    avg_col_name = f"Average_{chunk_idx}"
                    std_col_name = f"Std_Dev_{chunk_idx}"

                    if cols_for_math:
                        new_df[avg_col_name] = sig_df[cols_for_math].mean(axis=1)
                        new_df[std_col_name] = sig_df[cols_for_math].std(axis=1)
                    else:
                        new_df[avg_col_name] = pd.NA
                        new_df[std_col_name] = pd.NA

                    if chunk_idx not in master_dict:
                        master_dict[chunk_idx] = {"Nábojová hustota": f"{chunk_idx*10}"}

                    # Rows 582-702 = iloc[580:701]
                    avg_m2 = new_df[avg_col_name].iloc[580:701].mean()
                    std_m2 = new_df[std_col_name].iloc[580:701].mean()

                    master_dict[chunk_idx][f"{sig} Rovnovážná saturace"] = avg_m2
                    master_dict[chunk_idx][f"{sig} Odchylka rovnovážné saturace"] = std_m2

                sig_df = new_df

            # Populate Grand Mean row values for this sensor
            grand_mean_row[f"{sig} Rovnovážná saturace"] = pd.Series(all_baseline_avgs).mean()
            grand_mean_row[f"{sig} Odchylka rovnovážné saturace"] = pd.Series(all_baseline_stds).mean()

            sig_df.insert(0, "Čas", range(len(sig_df)))
            safe_sheet_name = re.sub(r'[\\/*?:\[\]]', '', sig)
            sheet_name = f"{safe_sheet_name}"[:31]
            sig_df.to_excel(writer, sheet_name=sheet_name, index=False)

        # Generate the Master Sheet
        if master_dict:
            master_df = pd.DataFrame.from_dict(master_dict, orient='index').sort_index()
            # Insert the Grand Mean row at the top
            final_master_df = pd.concat([pd.DataFrame([grand_mean_row]), master_df], ignore_index=True)
            final_master_df.to_excel(writer, sheet_name="Master_Summary", index=False)

# ==========================================
# GUI APPLICATION (TKINTER)
# ==========================================
def browse_input_excel():
    filepath = filedialog.askopenfilename(title="Select Input Excel File", filetypes=[("Excel Files", "*.xlsx *.xls")])
    if filepath:
        entry_in_excel.delete(0, tk.END)
        entry_in_excel.insert(0, filepath)

def browse_input_txt():
    filepath = filedialog.askopenfilename(title="Select Log File", filetypes=[("Text Files", "*.txt")])
    if filepath:
        entry_in_txt.delete(0, tk.END)
        entry_in_txt.insert(0, filepath)

def browse_output_excel():
    filepath = filedialog.asksaveasfilename(title="Save Output File As", defaultextension=".xlsx", filetypes=[("Excel Files", "*.xlsx")])
    if filepath:
        entry_out_excel.delete(0, tk.END)
        entry_out_excel.insert(0, filepath)

def run_script():
    in_excel = entry_in_excel.get()
    in_txt = entry_in_txt.get()
    out_excel = entry_out_excel.get()
    if not all([in_excel, in_txt, out_excel]):
        messagebox.showwarning("Missing Information", "Please select all three file paths.")
        return
    btn_run.config(state=tk.DISABLED, text="Processing...")
    root.update()
    try:
        process_measurement_data(in_excel, in_txt, out_excel, var_baseline.get(), var_stats.get())
        messagebox.showinfo("Success", "Process Complete.")
    except Exception as e:
        messagebox.showerror("Error", str(e))
    finally:
        btn_run.config(state=tk.NORMAL, text="Run Processing")

root = tk.Tk()
root.title("Data chopper")
root.geometry("650x300")
root.resizable(False, False)
pad_opts = {'padx': 10, 'pady': 5}

frame_files = tk.LabelFrame(root, text="File Selection", padx=10, pady=10)
frame_files.pack(fill="x", padx=10, pady=10)
tk.Label(frame_files, text="Input Excel:").grid(row=0, column=0, sticky="w", **pad_opts)
entry_in_excel = tk.Entry(frame_files, width=50)
entry_in_excel.grid(row=0, column=1, **pad_opts)
tk.Button(frame_files, text="Browse...", command=browse_input_excel).grid(row=0, column=2, **pad_opts)
tk.Label(frame_files, text="Input Log:").grid(row=1, column=0, sticky="w", **pad_opts)
entry_in_txt = tk.Entry(frame_files, width=50)
entry_in_txt.grid(row=1, column=1, **pad_opts)
tk.Button(frame_files, text="Browse...", command=browse_input_txt).grid(row=1, column=2, **pad_opts)
tk.Label(frame_files, text="Output File:").grid(row=2, column=0, sticky="w", **pad_opts)
entry_out_excel = tk.Entry(frame_files, width=50)
entry_out_excel.grid(row=2, column=1, **pad_opts)
tk.Button(frame_files, text="Browse...", command=browse_output_excel).grid(row=2, column=2, **pad_opts)

frame_options = tk.Frame(root)
frame_options.pack(pady=5)
var_baseline = tk.BooleanVar(value=True)
chk_baseline = tk.Checkbutton(frame_options, text="Baseline removal", variable=var_baseline)
chk_baseline.grid(row=0, column=0, padx=20)
var_stats = tk.BooleanVar(value=True)
chk_stats = tk.Checkbutton(frame_options, text="Average & Std Dev", variable=var_stats)
chk_stats.grid(row=0, column=1, padx=20)

btn_run = tk.Button(root, text="Run Processing", font=("Arial", 12, "bold"), bg="#4CAF50", command=run_script)
btn_run.pack(pady=5, ipadx=20, ipady=5)

if __name__ == "__main__":
    root.mainloop()