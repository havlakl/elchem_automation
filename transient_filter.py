import pandas as pd
import tkinter as tk
from tkinter import filedialog, messagebox

def browse_input():
    filename = filedialog.askopenfilename(
        title="Select Input Excel File",
        filetypes=(("Excel files", "*.xlsx *.xls"), ("All files", "*.*"))
    )
    input_entry.delete(0, tk.END)
    input_entry.insert(0, filename)

def browse_output():
    filename = filedialog.asksaveasfilename(
        title="Save Output Excel File As",
        defaultextension=".xlsx",
        filetypes=(("Excel files", "*.xlsx"), ("All files", "*.*"))
    )
    output_entry.delete(0, tk.END)
    output_entry.insert(0, filename)

def process_file():
    input_path = input_entry.get()
    output_path = output_entry.get()

    # 1. Validate N
    try:
        n = int(n_entry.get())
        if n <= 0:
            raise ValueError
    except ValueError:
        messagebox.showerror("Input Error", "Please enter a valid positive integer for N.")
        return

    # 2. Validate File Paths
    if not input_path or not output_path:
        messagebox.showerror("Input Error", "Please select both input and output file paths.")
        return

    # 3. Process the Excel File
    try:
        # sheet_name=None reads ALL sheets into a dictionary of DataFrames
        all_sheets = pd.read_excel(input_path, sheet_name=None)

        # Open an ExcelWriter to save multiple sheets to the same file
        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:

            # Loop through every sheet in the workbook
            for sheet_name, df in all_sheets.items():

                # If a sheet happens to have only 1 column, save it as-is to avoid breaking
                if len(df.columns) < 2:
                    df.to_excel(writer, sheet_name=sheet_name, index=False)
                    continue

                # Separate the first column from the rest
                first_column = df.iloc[:, 0]
                data_columns = df.iloc[:, 1:]

                # Calculate the N-row rolling average
                averaged_data = data_columns.rolling(window=n, min_periods=1).mean()

                # Combine the untouched first column with the new averaged data
                result_df = pd.concat([first_column, averaged_data], axis=1)

                # Write this specific sheet to the output workbook
                result_df.to_excel(writer, sheet_name=sheet_name, index=False)

        messagebox.showinfo("Success", f"File successfully processed!\nAll sheets saved to:\n{output_path}")

    except Exception as e:
        messagebox.showerror("Processing Error", f"An error occurred while processing the file:\n\n{str(e)}")

# --- UI Setup ---
root = tk.Tk()
root.title("Transient filter")
root.geometry("500x200")
root.resizable(False, False)

# Padding configuration
pad_options = {'padx': 10, 'pady': 10}

# Input File Row
tk.Label(root, text="Input File:").grid(row=0, column=0, sticky="e", **pad_options)
input_entry = tk.Entry(root, width=40)
input_entry.grid(row=0, column=1, **pad_options)
tk.Button(root, text="Browse", command=browse_input).grid(row=0, column=2, **pad_options)

# Output File Row
tk.Label(root, text="Output File:").grid(row=1, column=0, sticky="e", **pad_options)
output_entry = tk.Entry(root, width=40)
output_entry.grid(row=1, column=1, **pad_options)
tk.Button(root, text="Browse", command=browse_output).grid(row=1, column=2, **pad_options)

# N Value Row
tk.Label(root, text="N (Window Size):").grid(row=2, column=0, sticky="e", **pad_options)
n_entry = tk.Entry(root, width=10)
n_entry.insert(0, "3") # Default value
n_entry.grid(row=2, column=1, sticky="w", **pad_options)

# Run Button
run_button = tk.Button(root, text="Process", command=process_file, bg="#4CAF50", fg="white", font=("Arial", 10, "bold"))
run_button.grid(row=3, column=0, columnspan=3, pady=15)

# Start the application
root.mainloop()