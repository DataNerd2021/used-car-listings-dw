#!/usr/bin/python3
import pickle
import pandas as pd
from datetime import datetime

def load_zip_history():
    """Load zip code history from file"""
    try:
        with open('zip_code_history.pkl', 'rb') as f:
            return pickle.load(f)
    except FileNotFoundError:
        return []

def save_zip_history(history):
    """Save zip code history to file"""
    with open('zip_code_history.pkl', 'wb') as f:
        pickle.dump(history, f)

def clear_history():
    """Clear the zip code history"""
    save_zip_history([])
    print("Zip code history cleared!")

def view_history():
    """View current zip code history"""
    history = load_zip_history()
    if not history:
        print("No zip code history found.")
        return
    
    print(f"Current zip code history ({len(history)} entries):")
    for i, zip_code in enumerate(history, 1):
        print(f"  {i}. {zip_code}")

def add_to_history(zip_code):
    """Add a zip code to history"""
    history = load_zip_history()
    if zip_code not in history:
        history.append(zip_code)
        if len(history) > 10:  # Keep only last 10
            history.pop(0)
        save_zip_history(history)
        print(f"Added {zip_code} to history")
    else:
        print(f"{zip_code} is already in history")

def remove_from_history(zip_code):
    """Remove a zip code from history"""
    history = load_zip_history()
    if zip_code in history:
        history.remove(zip_code)
        save_zip_history(history)
        print(f"Removed {zip_code} from history")
    else:
        print(f"{zip_code} not found in history")

def show_available_zips():
    """Show which zip codes are available (not in history)"""
    # Load zip codes from CSV
    try:
        zips = pd.read_csv('zip_codes.csv')
        all_zips = zips['zip'].values.tolist()
    except FileNotFoundError:
        print("zip_codes.csv not found!")
        return
    
    history = load_zip_history()
    available_zips = [zip_code for zip_code in all_zips if zip_code not in history]
    
    print(f"Available zip codes ({len(available_zips)} out of {len(all_zips)}):")
    for zip_code in available_zips:
        print(f"  {zip_code}")

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python manage_zip_history.py view          - View current history")
        print("  python manage_zip_history.py clear         - Clear history")
        print("  python manage_zip_history.py available     - Show available zip codes")
        print("  python manage_zip_history.py add <zip>     - Add zip code to history")
        print("  python manage_zip_history.py remove <zip>  - Remove zip code from history")
        sys.exit(1)
    
    command = sys.argv[1].lower()
    
    if command == "view":
        view_history()
    elif command == "clear":
        clear_history()
    elif command == "available":
        show_available_zips()
    elif command == "add" and len(sys.argv) > 2:
        add_to_history(sys.argv[2])
    elif command == "remove" and len(sys.argv) > 2:
        remove_from_history(sys.argv[2])
    else:
        print("Invalid command or missing arguments")
        print("Use 'python manage_zip_history.py' for usage information") 