import os
import sys

# ==========================================
# MAC OS "INVISIBLE LIBRARY" FIX
# ==========================================
if sys.platform == "darwin":
    try:
        # 1. Locate the 'lib' folder inside your Conda environment
        # (This finds where python is running from, then goes up and into 'lib')
        base_path = os.path.dirname(sys.executable)
        lib_path = os.path.abspath(os.path.join(base_path, "..", "lib"))
        
        # 2. Tell macOS strictly: "Look here for the missing engines"
        # We append to both library paths to cover all bases
        current_dyld = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
        os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = f"{lib_path}:{current_dyld}"
        os.environ["DYLD_LIBRARY_PATH"] = f"{lib_path}:{os.environ.get('DYLD_LIBRARY_PATH', '')}"
        
        # 3. Optional: Print path to terminal so you can verify it worked
        print(f"✅ Mac Library Fix Applied: Pointing to {lib_path}")
        
    except Exception as e:
        print(f"⚠️ Library Fix Warning: {e}")
# ==========================================

import streamlit as st

# Initialize Session State variables if they don't exist
if 'extraction_done' not in st.session_state:
    st.session_state.extraction_done = False
if 'auto_matches' not in st.session_state:
    st.session_state.auto_matches = {}
if 'unmatched_data' not in st.session_state:
    st.session_state.unmatched_data = []
if 'manual_selections' not in st.session_state:
    st.session_state.manual_selections = {} # Stores { 'path_to_image': 'student_id' }
if 'swimming_matched' not in st.session_state:
    st.session_state.swimming_matched = {}
if 'swimming_unmatched' not in st.session_state:
    st.session_state.swimming_unmatched = []
if 'swimming_manual_selections' not in st.session_state:
    st.session_state.swimming_manual_selections = {} # Stores { 'swim_idx': 'student_id' }
if 'dietary_matched' not in st.session_state:
    st.session_state.dietary_matched = {}
if 'dietary_unmatched' not in st.session_state:
    st.session_state.dietary_unmatched = []
if 'dietary_manual_selections' not in st.session_state:
    st.session_state.dietary_manual_selections = {} # Stores { 'dietary_idx': 'student_id' }
import pandas as pd
import zipfile
import yaml
import urllib.parse
import re
import base64
import pdfplumber
from io import BytesIO
from PIL import Image
from datetime import datetime
from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML
from pypdf import PdfWriter, PdfReader

# ---------------- CONFIG ----------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")
TEMP_DIR = os.path.join(BASE_DIR, "_temp")
os.makedirs(TEMP_DIR, exist_ok=True)

st.set_page_config(
    page_title="Medical Booklet Creator",
    layout="wide",
    page_icon="📋",
    menu_items={
        "Get help": None,
        "Report a bug": None,
        "About": None
    }
)

try:
    with open("config.yaml", "r") as f:
        CONFIG = yaml.safe_load(f)
except FileNotFoundError:
    st.error("config.yaml not found.")
    st.stop()

COLS = CONFIG["column_mappings"]
SEVERITY_KEYWORDS = CONFIG["severity_keywords"]

# ---------------- DATA DICTIONARIES ----------------
LEARNING_CODES = {
    "!Time": "Extra Time",
    "!RstBrk": "Rest Breaks",
    "!RstBrks": "Rest Breaks",
    "!RestBreak": "Rest Breaks",
    "!IndvRm": "Separate Room",
    "!SmallRoom": "Small Room",
    "!Calculator": "Calculator",
    "!Scribe": "Scribe",
    "!Rdr": "Reader",
    "!Reader": "Reader",
    "!Laptop": "Laptop Allowed",
    "!Music": "Music Allowed",
    "!Prompt": "Prompter",
    "!Typing": "Typing Allowed",
    "!VocText": "Voice-to-Text",
    "!Grammar": "Grammar Support",
    "!Sensory": "Sensory Breaks",
    "!Extension": "Extension Tasks",
    "!AstTech": "Assistive Technology",
    "!Spelling": "Spelling Support"
}

GLOSSARY = {
    "SLD": "Specific Learning Disorder",
    "ASD": "Autism Spectrum Disorder",
    "DCD": "Developmental Coordination Disorder"
}

# ---------------- HELPERS ----------------
def img_to_base64(path):
    if not path or not os.path.exists(path): return None
    with open(path, "rb") as f: return base64.b64encode(f.read()).decode()

def parse_tutor(text):
    """Extracts Tutor name from General Notes."""
    if not isinstance(text, str): return ""
    # Looks for "Tutor:" followed by text
    match = re.search(r'Tutor:\s*(.*)', text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return ""

def convert_file_to_images(file_obj):
    """
    Converts a file (PDF or Image) into a list of Base64 strings (one per page).
    PDFs are converted to high-resolution images to preserve quality at A4 size.
    This allows them to be embedded directly into the HTML in the correct position.
    
    CRITICAL FIX: Always seeks to beginning and reads file contents into memory first
    to avoid file pointer issues when the same file is referenced multiple times.
    """
    images_b64 = []
    try:
        # CRITICAL: Read entire file into memory first to avoid file pointer issues
        file_obj.seek(0)
        file_bytes = file_obj.read()
        file_buffer = BytesIO(file_bytes)
        
        # 1. Handle PDF Attachments - Convert to high-res images
        if file_obj.name.lower().endswith('.pdf'):
            with pdfplumber.open(file_buffer) as pdf:
                for page in pdf.pages:
                    # Render page to image at higher resolution for A4 quality
                    # 200 DPI gives good quality for A4 medical documents
                    im = page.to_image(resolution=200).original.convert("RGB")
                    
                    buf = BytesIO()
                    im.save(buf, format="JPEG", quality=90)
                    b64 = base64.b64encode(buf.getvalue()).decode()
                    images_b64.append(b64)
                    
        # 2. Handle Image Attachments (JPG, PNG)
        else:
            img = Image.open(file_buffer).convert("RGB")
            buf = BytesIO()
            img.save(buf, format="JPEG", quality=90)
            b64 = base64.b64encode(buf.getvalue()).decode()
            images_b64.append(b64)
            
    except Exception as e:
        print(f"Error converting file {file_obj.name}: {e}")
        
    return images_b64

def detect_medical_plans(df):
    """
    Parses 'Medical notes' to find 'Action or medical plan links' and URLs.
    Returns: { student_id: [ {'condition': 'ALLERGIES', 'url': 'https://...', 'details': '...'} ] }
    """
    plans_needed = {}
    
    for _, row in df.iterrows():
        sid = str(row[COLS['student_id']])
        notes = str(row.get(COLS['medical_notes'], ""))
        
        if not notes: continue
        
        student_plans = []
        
        # 1. Parse specific "Action or medical plan links" section
        # We normalize whitespace to handle the split lines in your example
        clean_notes = notes.replace('\n', '').replace('\r', '')
        
        # Look for the block starting with "Action or medical plan links:" 
        # and ending at the next number or separator
        if "Action or medical plan links:" in clean_notes:
            try:
                # Extract the bit between the header and the next section (often starting with a digit like "4 Medical Conditions")
                start_marker = "Action or medical plan links:"
                start_idx = clean_notes.find(start_marker) + len(start_marker)
                
                # Find end - heuristic: look for "Medical Conditions" or "-----------"
                end_idx = len(clean_notes)
                for marker in ["Medical Conditions", "-----------"]:
                    idx = clean_notes.find(marker, start_idx)
                    if idx != -1 and idx < end_idx:
                        end_idx = idx
                
                # Get the chunk containing links
                links_chunk = clean_notes[start_idx:end_idx]
                
                # Split by ';' as per your data example
                entries = links_chunk.split(';')
                
                for entry in entries:
                    if "http" in entry:
                        # Format is usually "CONDITION: https://url"
                        # Regex to pull the name and the url
                        # Name is everything before 'http'
                        parts = entry.split('http')
                        name = parts[0].strip().strip(':').strip()
                        url = 'http' + parts[1].strip()
                        
                        student_plans.append({
                            "condition": name,
                            "url": url,
                            "details": "Link found in medical notes."
                        })
            except Exception as e:
                print(f"Error parsing plans for {sid}: {e}")

        # 2. Fallback: If no links found, check for "Action plan available" text phrases
        if not student_plans and "plan" in notes.lower():
             blocks = re.split(r'(?:Condition:|-----------)', notes)
             for block in blocks:
                 if "plan" in block.lower() and "available" in block.lower():
                     lines = block.strip().split('\n')
                     cond_name = lines[0].split('(')[0].strip()
                     if len(cond_name) > 30: cond_name = "Medical Condition"
                     
                     # Create a generic search link if no specific URL found
                     base_url = CONFIG['app_settings']['school_portal_url']
                     if base_url.endswith('/'): base_url = base_url[:-1]
                     search_link = f"{base_url}/search?id={sid}"
                     
                     student_plans.append({
                         "condition": cond_name,
                         "url": search_link, 
                         "details": block.strip()
                     })

        if student_plans:
            plans_needed[sid] = student_plans

    return plans_needed

def parse_medical_text(text):
    if not isinstance(text, str) or not text.strip(): return []
    text = text.replace('\r\n', '\n')
    blocks = re.split(r'-{3,}', text)
    parsed_conditions = []

    for block in blocks:
        block = block.strip()
        if not block: continue
        if "Condition:" in block:
            match = re.search(r'Condition:\s*(.+?)\s*\(Severity level:\s*(.+?)\)', block)
            if match:
                cond_name = match.group(1).strip()
                severity = match.group(2).strip()
                desc_start = match.end()
                description = block[desc_start:].strip()
                
                # CSS Class determination
                css_class = "mild" 
                s_lower = severity.lower()
                
                # --- UPDATE: Force Wording "Severe/Life Threatening" ---
                if any(x in s_lower for x in ["life threatening", "severe", "anaphylaxis"]): 
                    css_class = "severe"
                    severity = "Severe/Life Threatening" # Exact wording update
                elif "moderate" in s_lower: 
                    css_class = "moderate"

                parsed_conditions.append({
                    "name": cond_name, "severity": severity, "description": description, "css_class": css_class
                })
    
    if not parsed_conditions and len(text) > 10 and "No data" not in text:
        parsed_conditions.append({
            "name": "General Medical Note", "severity": "Info", "description": text, "css_class": "mild"
        })
    return parsed_conditions

def parse_doctors(text):
    """Parses doctor info into a structured list with map links."""
    if not isinstance(text, str) or not text.strip(): return []
    
    doctors = []
    # Split by "DOCTOR X:" or just "DOCTOR:" pattern
    entries = re.split(r'DOCTOR \d*:', text, flags=re.IGNORECASE)
    
    for entry in entries:
        entry = entry.strip()
        if not entry: continue
        
        lines = entry.split('\n')
        name = lines[0].strip()
        
        # Change default to "Not Listed"
        address = "Not Listed"
        phone = "Not Listed"
        
        for line in lines:
            if "Address:" in line:
                val = line.replace("Address:", "").strip()
                if val: address = val
            if "Telephone:" in line:
                val = line.replace("Telephone:", "").strip()
                if val: phone = val

        # Handle Map Link
        map_link = None
        if address != "Not Listed":
            map_query = urllib.parse.quote(address)
            map_link = f"https://www.google.com/maps/search/?api=1&query={map_query}"
        
        # Handle Phone Link
        phone_link = None
        if phone != "Not Listed":
            phone_clean = re.sub(r'[^0-9]', '', phone)
            if phone_clean:
                phone_link = f"tel:{phone_clean}"
        
        doctors.append({
            "name": name,
            "address": address,
            "map_link": map_link,
            "phone_display": phone,
            "phone_link": phone_link
        })
        
    return doctors

def parse_emergency_contacts(text):
    if not isinstance(text, str) or not text.strip(): return []
    contacts = []
    raw_blocks = re.split(r'EMERGENCY \d+:', text)
    
    for block in raw_blocks:
        block = block.strip()
        if not block: continue
        lines = block.split('\n')
        name = lines[0].strip()
        relation = "Unknown"
        phone = ""
        for line in lines:
            if "Relationship:" in line: relation = line.split("Relationship:")[-1].strip()
            if "Telephone:" in line:
                phone_raw = line.split("Telephone:")[-1].strip()
                phone_clean = re.sub(r'[^\d+]', '', phone_raw) 
                phone = {"display": phone_raw, "link": f"tel:{phone_clean}"}
        if phone: contacts.append({"name": name, "relation": relation, "phone": phone})
    return contacts

def parse_home_contacts(row):
    """
    Parses home contact information from the contact file columns.
    Returns a dictionary with contacts list and home information.
    Safely handles missing columns by returning empty values.
    """
    if not isinstance(row, pd.Series):
        return {"contacts": [], "home_address": "", "home_phone": ""}
    
    try:
        c_map = CONFIG.get('contact_file_mappings', {})
        contacts = []
        
        # Student Contact 1
        sc1_first = str(row.get(c_map.get('sc1_name_pref', 'SC1 Preferred'), '')).strip()
        sc1_last = str(row.get(c_map.get('sc1_name_sur', 'SC1 Surname'), '')).strip()
        sc1_mobile = str(row.get(c_map.get('sc1_mobile', 'SC1 Mobile'), '')).strip()
        
        # Only add if we have actual data (not just empty strings or 'nan')
        if (sc1_first and sc1_first.lower() != 'nan') or (sc1_last and sc1_last.lower() != 'nan'):
            name = f"{sc1_first} {sc1_last}".strip()
            if name and name.lower() != 'nan':  # Extra check for valid name
                phone_clean = re.sub(r'[^\d+]', '', sc1_mobile) if (sc1_mobile and sc1_mobile.lower() != 'nan') else ""
                phone_obj = {"display": sc1_mobile, "link": f"tel:{phone_clean}"} if phone_clean else None
                
                contacts.append({
                    "name": name,
                    "relation": "Student Contact 1",
                    "phone": phone_obj
                })
        
        # Student Contact 2
        sc2_first = str(row.get(c_map.get('sc2_name_pref', 'SC2 Preferred'), '')).strip()
        sc2_last = str(row.get(c_map.get('sc2_name_sur', 'SC2 Surname'), '')).strip()
        sc2_mobile = str(row.get(c_map.get('sc2_mobile', 'SC2 Mobile'), '')).strip()
        
        if (sc2_first and sc2_first.lower() != 'nan') or (sc2_last and sc2_last.lower() != 'nan'):
            name = f"{sc2_first} {sc2_last}".strip()
            if name and name.lower() != 'nan':
                phone_clean = re.sub(r'[^\d+]', '', sc2_mobile) if (sc2_mobile and sc2_mobile.lower() != 'nan') else ""
                phone_obj = {"display": sc2_mobile, "link": f"tel:{phone_clean}"} if phone_clean else None
                
                contacts.append({
                    "name": name,
                    "relation": "Student Contact 2",
                    "phone": phone_obj
                })
        
        # Home Information
        home_address = str(row.get(c_map.get('address', 'Contact Address'), '')).strip()
        home_phone = str(row.get(c_map.get('home_phone', 'Home Phone'), '')).strip()
        
        # Clean up 'nan' strings
        if home_address.lower() == 'nan':
            home_address = ""
        if home_phone.lower() == 'nan':
            home_phone = ""
        
        return {
            "contacts": contacts,
            "home_address": home_address,
            "home_phone": home_phone
        }
    except Exception as e:
        # If anything goes wrong, return empty structure
        print(f"Error parsing home contacts: {e}")
        return {"contacts": [], "home_address": "", "home_phone": ""}

def parse_emergency_contact_names(emergency_text):
    """
    Extracts names from emergency contact text in Student List CSV.
    Returns list of full names (first + last) in lowercase.
    
    Example input:
    "EMERGENCY 1: Jessica Gray
    Relationship: Mother
    Telephone: 0400 765 567
    
    EMERGENCY 2: George Gray
    Relationship: Father"
    
    Returns: ["jessica gray", "george gray"]
    """
    if not isinstance(emergency_text, str):
        return []
    
    names = []
    # Find all "EMERGENCY X: Name" patterns
    # Updated regex to only capture non-empty names (at least one word character)
    pattern = r'EMERGENCY \d+:\s*([A-Za-z][A-Za-z\s\-\']+?)(?:\n|$)'
    matches = re.findall(pattern, emergency_text)
    
    for name in matches:
        name = name.strip()
        # Additional validation: must have at least 2 characters and not be just whitespace
        if name and len(name) >= 2 and name.lower() not in ['not supplied', 'relationship:', 'telephone:']:
            # Convert to lowercase for matching
            names.append(name.lower())
    
    return names

def match_swimming_ability(df_main, swimming_csv, contact_df=None):
    """
    Matches swimming ability data to students by searching for student names in the swimming CSV.
    
    Strategy:
    1. Iterate through each student in the student list
    2. Check if multiple students share the same surname (duplicates)
    3. For unique surnames: search for surname in swimming CSV student name
    4. For duplicate surnames: search for "surname + preferred name" or "surname + first name"
    5. Unmatched students can be manually assigned in the UI
    
    Returns: (matched_dict, unmatched_list)
    - matched_dict: {student_id: swimming_ability}
    - unmatched_list: [{student_name, ability, index}] - unmatched swimming records
    """
    if swimming_csv is None:
        print("\n⚠️  No swimming CSV provided - skipping swimming ability matching")
        return {}, []
    
    try:
        # Reset file pointer if it's a file object
        if hasattr(swimming_csv, 'seek'):
            swimming_csv.seek(0)
        
        # CRITICAL FIX: The swimming CSV header has 6 column names but data has 7 columns
        # The header is missing the column name for the "Submitted" status column
        # We need to provide the correct column names
        correct_columns = ['Email', 'First Name', 'Surname', 'Student', 'Submission Time', 'Submitted Status', 'Swimming Ability']
        
        try:
            # Try reading with correct column names
            swim_df = pd.read_csv(swimming_csv, names=correct_columns, skiprows=1).fillna("")
            print(f"✓ CSV read with corrected column structure (7 columns)")
        except:
            # Fallback to normal read if that doesn't work
            if hasattr(swimming_csv, 'seek'):
                swimming_csv.seek(0)
            swim_df = pd.read_csv(swimming_csv).fillna("")
            print(f"⚠️  Using standard CSV read")
        
        swim_map = CONFIG.get('swimming_file_mappings', {})
        
        matched = {}
        unmatched = []
        used_swim_indices = set()  # Track which swimming records have been matched
        
        # Get column names
        student_col = swim_map.get('student_name', 'Student')
        
        # For the corrected CSV structure, ability is in "Swimming Ability" column
        # (not an unnamed column anymore since we provided correct names)
        ability_col = 'Swimming Ability'
        
        # Verify the column exists and has valid data
        if ability_col in swim_df.columns and len(swim_df) > 0:
            sample = str(swim_df[ability_col].iloc[0]).lower()
            # Check if it contains actual swimming ability keywords
            if not any(keyword in sample for keyword in ['swimmer', 'cannot swim', 'competent', 'weak', 'fair', 'strong']):
                # If not, fall back to looking for unnamed columns or last column
                print(f"⚠️  '{ability_col}' doesn't contain swimming data, searching for correct column...")
                for col in swim_df.columns:
                    if 'Unnamed' in str(col):
                        ability_col = col
                        break
                if ability_col == 'Swimming Ability':  # Still not found
                    ability_col = swim_df.columns[-1]
        
        print(f"\n{'='*80}")
        print("SWIMMING ABILITY MATCHING - STUDENT-FIRST METHOD")
        print(f"{'='*80}")
        print(f"Swimming CSV columns: {list(swim_df.columns)}")
        print(f"  student_name column: '{student_col}'")
        print(f"  ability column: '{ability_col}'")
        if len(swim_df) > 0:
            print(f"\nSample swimming record:")
            print(f"  {student_col}: '{swim_df[student_col].iloc[0]}'")
            print(f"  {ability_col}: '{swim_df[ability_col].iloc[0]}'")
        print(f"\nTotal swimming records: {len(swim_df)}")
        print(f"Total students in main DF: {len(df_main)}")
        
        # STEP 1: Identify students with duplicate surnames
        surname_counts = {}
        for _, row in df_main.iterrows():
            surname = str(row[COLS['surname']]).strip().lower()
            if surname:
                surname_counts[surname] = surname_counts.get(surname, 0) + 1
        
        duplicate_surnames = {s for s, count in surname_counts.items() if count > 1}
        print(f"\nFound {len(duplicate_surnames)} surnames with multiple students (will need first name matching)")
        if duplicate_surnames and len(duplicate_surnames) <= 10:
            print(f"  Duplicate surnames: {', '.join(sorted(duplicate_surnames))}")
        
        print(f"\n{'='*80}")
        print("MATCHING PROCESS")
        print(f"{'='*80}")
        
        # STEP 2: Iterate through each student and try to find them in swimming CSV
        matched_count = 0
        for student_idx, student_row in df_main.iterrows():
            student_id = str(student_row[COLS['student_id']])
            first_name = str(student_row[COLS['first_name']]).strip()
            preferred_name = str(student_row.get('Preferred name', '')).strip()
            surname = str(student_row[COLS['surname']]).strip()
            
            if not surname:
                continue
            
            surname_lower = surname.lower()
            first_lower = first_name.lower()
            pref_lower = preferred_name.lower()
            
            # Determine if this student has a duplicate surname
            has_duplicate_surname = surname_lower in duplicate_surnames
            
            # Search through swimming CSV for this student
            match_found = False
            for swim_idx, swim_row in swim_df.iterrows():
                # Skip if already matched
                if swim_idx in used_swim_indices:
                    continue
                
                student_name_swim = str(swim_row.get(student_col, '')).strip().lower()
                ability = str(swim_row.get(ability_col, '')).strip()
                
                # Skip invalid ability values
                if not ability or ability.lower() in ['nan', 'submitted', '']:
                    continue
                
                # For students with unique surnames: just check if surname appears in the name
                # Use word boundary matching to avoid "Bell" matching "Bella"
                if not has_duplicate_surname:
                    # Check if surname appears as a complete word (not substring)
                    surname_pattern = r'\b' + re.escape(surname_lower) + r'\b'
                    if re.search(surname_pattern, student_name_swim):
                        matched[student_id] = ability
                        used_swim_indices.add(swim_idx)
                        match_found = True
                        matched_count += 1
                        if matched_count <= 5:
                            print(f"[{matched_count}] ✓ {surname}, {first_name} (ID: {student_id})")
                            print(f"    Matched to: '{swim_row.get(student_col, '')}' → {ability}")
                            print(f"    (Unique surname match)")
                        break
                
                # For students with duplicate surnames: check surname AND first name (or preferred)
                # Use word boundary matching to avoid partial matches
                else:
                    surname_pattern = r'\b' + re.escape(surname_lower) + r'\b'
                    surname_match = re.search(surname_pattern, student_name_swim)
                    
                    first_pattern = r'\b' + re.escape(first_lower) + r'\b' if first_lower else None
                    first_match = first_pattern and re.search(first_pattern, student_name_swim)
                    
                    pref_pattern = r'\b' + re.escape(pref_lower) + r'\b' if pref_lower else None
                    pref_match = pref_pattern and re.search(pref_pattern, student_name_swim)
                    
                    if surname_match and (first_match or pref_match):
                        matched[student_id] = ability
                        used_swim_indices.add(swim_idx)
                        match_found = True
                        matched_count += 1
                        match_type = "first name" if first_match else "preferred name"
                        if matched_count <= 5:
                            print(f"[{matched_count}] ✓ {surname}, {first_name} (ID: {student_id})")
                            print(f"    Matched to: '{swim_row.get(student_col, '')}' → {ability}")
                            print(f"    (Surname + {match_type} match)")
                        break
            
            if not match_found and matched_count <= 10:
                # Show debug info for unmatched students
                if has_duplicate_surname:
                    print(f"[ ] ✗ {surname}, {first_name} (Pref: {preferred_name}) (ID: {student_id})")
                    print(f"    Reason: Duplicate surname - needs surname + first/preferred name match")
                else:
                    print(f"[ ] ✗ {surname}, {first_name} (ID: {student_id}) - Unique surname but not found in swimming CSV")
        
        # STEP 3: Collect unmatched swimming records for manual assignment
        for swim_idx, swim_row in swim_df.iterrows():
            if swim_idx not in used_swim_indices:
                student_name_swim = str(swim_row.get(student_col, '')).strip()
                ability = str(swim_row.get(ability_col, '')).strip()
                
                # Only add to unmatched if it has valid data
                if student_name_swim and ability and ability.lower() not in ['nan', 'submitted', '']:
                    unmatched.append({
                        'student_name': student_name_swim,
                        'ability': ability,
                        'index': swim_idx
                    })
        
        print(f"\n{'='*80}")
        print("MATCHING RESULTS")
        print(f"{'='*80}")
        print(f"✓ Matched: {len(matched)} students")
        print(f"✗ Unmatched: {len(unmatched)} swimming records need manual assignment")
        
        if matched and len(matched) > 5:
            print(f"\n... and {len(matched)-5} more students matched")
        
        if unmatched:
            print(f"\nFirst 5 unmatched swimming records:")
            for item in unmatched[:5]:
                print(f"  '{item['student_name']}' → {item['ability']}")
            if len(unmatched) > 5:
                print(f"  ... and {len(unmatched)-5} more")
        
        print(f"{'='*80}\n")
        
        return matched, unmatched
        
    except Exception as e:
        st.error(f"Error processing swimming CSV: {e}")
        import traceback
        print(traceback.format_exc())
        return {}, []

def get_swimming_display_color(ability):
    """
    Returns color class based on swimming ability.
    """
    if not ability or ability.lower() == 'data not recorded':
        return 'swim-none'
    elif 'cannot swim' in ability.lower():
        return 'swim-cannot'
    elif 'weak swimmer' in ability.lower():
        return 'swim-weak'
    else:
        return 'swim-ok'

def match_dietary_requirements(df_main, dietary_csv, contact_csv=None):
    """
    Matches students from the main CSV with dietary requirements from the dietary CSV.
    Uses word boundary matching to avoid partial matches (e.g., "Bell" vs "Bella").
    
    Args:
        df_main: Main student dataframe
        dietary_csv: Uploaded dietary CSV file
        contact_csv: Optional contact CSV (not used but kept for consistency)
    
    Returns:
        matched: Dict of {student_id: dietary_requirement}
        unmatched: List of dicts with unmatched dietary records
    """
    try:
        # Read the dietary CSV
        # Note: The CSV has 7 columns in data but only 6 in header (extra "Submitted" column)
        # We need to provide column names manually to handle this
        if hasattr(dietary_csv, 'seek'):
            dietary_csv.seek(0)
        
        # Provide explicit column names including the unlabeled "Submitted" column
        col_names = ['Email', 'First Name', 'Surname', 'Student', 'Submission Time', 'Submitted', 'Dietary Requirements']
        dietary_df = pd.read_csv(dietary_csv, names=col_names, skiprows=1).fillna("")
        
        matched = {}
        unmatched = []
        used_dietary_indices = set()
        
        # Get column names - the student name is in "Student" column
        student_col = 'Student'
        
        # The dietary requirements are in the last column
        dietary_col = 'Dietary Requirements'
        
        # Check if we have the expected columns
        if student_col not in dietary_df.columns:
            print(f"⚠️  Warning: '{student_col}' column not found in dietary CSV")
            print(f"    Available columns: {list(dietary_df.columns)}")
            return {}, []
        
        print(f"\n{'='*80}")
        print("DIETARY REQUIREMENTS MATCHING - STUDENT-FIRST METHOD")
        print(f"{'='*80}")
        print(f"Dietary CSV columns: {list(dietary_df.columns)}")
        print(f"  student_name column: '{student_col}'")
        print(f"  dietary column: '{dietary_col}'")
        if len(dietary_df) > 0:
            print(f"\nSample dietary record:")
            print(f"  {student_col}: '{dietary_df[student_col].iloc[0]}'")
            if dietary_col in dietary_df.columns:
                print(f"  {dietary_col}: '{str(dietary_df[dietary_col].iloc[0])[:100]}...'")
        print(f"\nTotal dietary records: {len(dietary_df)}")
        print(f"Total students in main DF: {len(df_main)}")
        
        # STEP 1: Identify students with duplicate surnames
        surname_counts = {}
        for _, row in df_main.iterrows():
            surname = str(row[COLS['surname']]).strip().lower()
            if surname:
                surname_counts[surname] = surname_counts.get(surname, 0) + 1
        
        duplicate_surnames = {s for s, count in surname_counts.items() if count > 1}
        print(f"\nFound {len(duplicate_surnames)} surnames with multiple students (will need first name matching)")
        if duplicate_surnames and len(duplicate_surnames) <= 10:
            print(f"  Duplicate surnames: {', '.join(sorted(duplicate_surnames))}")
        
        print(f"\n{'='*80}")
        print("MATCHING PROCESS")
        print(f"{'='*80}")
        
        # STEP 2: Iterate through each student and try to find them in dietary CSV
        matched_count = 0
        for student_idx, student_row in df_main.iterrows():
            student_id = str(student_row[COLS['student_id']])
            first_name = str(student_row[COLS['first_name']]).strip()
            preferred_name = str(student_row.get('Preferred name', '')).strip()
            surname = str(student_row[COLS['surname']]).strip()
            
            if not surname:
                continue
            
            surname_lower = surname.lower()
            first_lower = first_name.lower()
            pref_lower = preferred_name.lower()
            
            # Determine if this student has a duplicate surname
            has_duplicate_surname = surname_lower in duplicate_surnames
            
            # Search through dietary CSV for this student
            match_found = False
            for dietary_idx, dietary_row in dietary_df.iterrows():
                # Skip if already matched
                if dietary_idx in used_dietary_indices:
                    continue
                
                student_name_dietary = str(dietary_row.get(student_col, '')).strip().lower()
                dietary_req = str(dietary_row.get(dietary_col, '')).strip()
                
                # Check if dietary value is empty/N/A (form filled but no concerns)
                # vs actually having content
                if not dietary_req or dietary_req.lower() in ['nan', 'submitted', '']:
                    dietary_req = "No concerns listed"  # They filled the form but no issues
                elif dietary_req.lower() == 'n/a':
                    dietary_req = "No concerns listed"  # Explicitly said N/A
                
                # For students with unique surnames: check if surname appears as a complete word
                # Use word boundary matching to avoid "Bell" matching "Bella"
                if not has_duplicate_surname:
                    surname_pattern = r'\b' + re.escape(surname_lower) + r'\b'
                    if re.search(surname_pattern, student_name_dietary):
                        matched[student_id] = dietary_req
                        used_dietary_indices.add(dietary_idx)
                        match_found = True
                        matched_count += 1
                        if matched_count <= 5:
                            print(f"[{matched_count}] ✓ {surname}, {first_name} (ID: {student_id})")
                            print(f"    Matched to: '{dietary_row.get(student_col, '')}' → {dietary_req[:50]}...")
                            print(f"    (Unique surname match)")
                        break
                
                # For students with duplicate surnames: check surname AND first name (or preferred)
                # Use word boundary matching to avoid partial matches
                else:
                    surname_pattern = r'\b' + re.escape(surname_lower) + r'\b'
                    surname_match = re.search(surname_pattern, student_name_dietary)
                    
                    first_pattern = r'\b' + re.escape(first_lower) + r'\b' if first_lower else None
                    first_match = first_pattern and re.search(first_pattern, student_name_dietary)
                    
                    pref_pattern = r'\b' + re.escape(pref_lower) + r'\b' if pref_lower else None
                    pref_match = pref_pattern and re.search(pref_pattern, student_name_dietary)
                    
                    if surname_match and (first_match or pref_match):
                        matched[student_id] = dietary_req
                        used_dietary_indices.add(dietary_idx)
                        match_found = True
                        matched_count += 1
                        match_type = "first name" if first_match else "preferred name"
                        if matched_count <= 5:
                            print(f"[{matched_count}] ✓ {surname}, {first_name} (ID: {student_id})")
                            print(f"    Matched to: '{dietary_row.get(student_col, '')}' → {dietary_req[:50]}...")
                            print(f"    (Surname + {match_type} match)")
                        break
            
            if not match_found and matched_count <= 10:
                # Show debug info for unmatched students
                if has_duplicate_surname:
                    print(f"[ ] ✗ {surname}, {first_name} (Pref: {preferred_name}) (ID: {student_id})")
                    print(f"    Reason: Duplicate surname - needs surname + first/preferred name match")
                else:
                    print(f"[ ] ✗ {surname}, {first_name} (ID: {student_id}) - Unique surname but not found in dietary CSV")
        
        # STEP 3: Collect unmatched dietary records for manual assignment
        for dietary_idx, dietary_row in dietary_df.iterrows():
            if dietary_idx not in used_dietary_indices:
                student_name_dietary = str(dietary_row.get(student_col, '')).strip()
                dietary_req = str(dietary_row.get(dietary_col, '')).strip()
                
                # Convert empty/N/A to "No concerns listed"
                if not dietary_req or dietary_req.lower() in ['nan', 'submitted', '', 'n/a']:
                    dietary_req = "No concerns listed"
                
                # Only add to unmatched if it has a student name
                if student_name_dietary:
                    unmatched.append({
                        'student_name': student_name_dietary,
                        'dietary_req': dietary_req,
                        'index': dietary_idx
                    })
        
        print(f"\n{'='*80}")
        print("MATCHING RESULTS")
        print(f"{'='*80}")
        print(f"✓ Matched: {len(matched)} students")
        print(f"✗ Unmatched: {len(unmatched)} dietary records need manual assignment")
        
        if matched and len(matched) > 5:
            print(f"\n... and {len(matched)-5} more students matched")
        
        if unmatched:
            print(f"\nFirst 5 unmatched dietary records:")
            for item in unmatched[:5]:
                print(f"  '{item['student_name']}' → {item['dietary_req'][:50]}...")
            if len(unmatched) > 5:
                print(f"  ... and {len(unmatched)-5} more")
        
        print(f"{'='*80}\n")
        
        return matched, unmatched
        
    except Exception as e:
        st.error(f"Error processing dietary CSV: {e}")
        import traceback
        print(traceback.format_exc())
        return {}, []

def get_swimming_display_color(ability):
    """
    Returns color class based on swimming ability.
    """
    if not ability or ability.lower() == 'data not recorded':
        return 'swim-none'
    elif 'cannot swim' in ability.lower():
        return 'swim-cannot'
    elif 'weak swimmer' in ability.lower():
        return 'swim-weak'
    else:
        return 'swim-ok'

def parse_learning_support(text):
    if not isinstance(text, str) or not text.strip(): return {} 

    # 0. GLOSSARY EXPANSION
    for acro, full in GLOSSARY.items():
        pattern = r'\b' + re.escape(acro) + r'\b'
        text = re.sub(pattern, full, text, flags=re.IGNORECASE)

    # 1. EXTRACT BADGES
    raw_codes = set(re.findall(r'(![A-Za-z]+)', text))
    clean_badges = []
    for code in raw_codes:
        label = LEARNING_CODES.get(code, code.replace("!", ""))
        clean_badges.append(label)
        text = text.replace(code, "")

    lines = text.split('\n')
    cleaned_lines = []
    
    line_killers = [
        "Synchronised from Paperly", "Last changed", "AEDT", "AEST", 
        "See ILP", "refer to Learning Profile", "found in the Student Plans", 
        "No Medical Conditions", "Educational assessment report on file",
        "An ILP will be added", "Effective August", "Effective 20"
    ]
    
    prefixes_to_strip = [
        "Learning Alert Diagnosis:", "Learning Alert:", "Diagnosis:", 
        "Adjustments:", "Accomodations:", "Accommodations:",
        "Considerations:", "Condition:"
    ]

    for line in lines:
        line_clean = line.strip()
        if not line_clean: continue
        
        if any(killer.lower() in line_clean.lower() for killer in line_killers):
            continue

        if line_clean.lower() == "learning alert":
            continue

        for prefix in prefixes_to_strip:
            if line_clean.lower().startswith(prefix.lower()):
                pattern = re.compile(re.escape(prefix), re.IGNORECASE)
                line_clean = pattern.sub("", line_clean, count=1).strip()

        line_clean = re.sub(r'[\s,]{2,}', ', ', line_clean)
        line_clean = line_clean.strip(" :,-")

        if line_clean:
            cleaned_lines.append(line_clean)

    seen = set()
    final_lines = []
    for x in cleaned_lines:
        if x not in seen:
            final_lines.append(x)
            seen.add(x)

    diagnosis_desc = "\n".join(final_lines)

    return {
        "diagnosis": diagnosis_desc if diagnosis_desc else "See Student Plans for details.",
        "accommodations": sorted(clean_badges)
    }

# ---------------------------------------------------------------------------
# Ligature / unknown-glyph map.
# The FB-block entries are standard Unicode ligatures.
# The LIGATURE_MAP at module level is checked first; then any char
# in the PUA range (E000-F8FF) that is NOT in the map is treated as
# "tt" as a fallback (the most common unmapped school-photo glyph).
# ---------------------------------------------------------------------------
LIGATURE_MAP = {
    "\ufb00": "ff",
    "\ufb01": "fi",
    "\ufb02": "fl",
    "\ufb03": "ffi",
    "\ufb04": "ffl",
    "\ufb05": "st",
    "\ufb06": "st",
}

# Accumulates any PUA chars we actually encounter, for the debug log.
_SEEN_PUA_CHARS = set()


def clean_ligatures(text):
    """
    Centralised ligature / glyph cleanup.
    1. Known ligatures (FB block) are replaced by their expansions.
    2. ANY Private-Use-Area character (U+E000–U+F8FF) not already in
       LIGATURE_MAP is assumed to be 'tt' (by far the most common
       unmapped glyph in school-photo PDFs) and replaced accordingly.
       The char is also logged to _SEEN_PUA_CHARS for the debug dump.
    3. Zero-width / invisible formatting chars are stripped.
    4. Any run of 3+ identical letters is collapsed to exactly 2.
       This handles pdfplumber emitting phantom duplicate chars after
       a ligature glyph (e.g. [PUA]+"tt" -> "tttt" collapses to "tt").
       No English surname has 3+ of the same letter in a row.
    """
    out = []
    for ch in text:
        cp = ord(ch)
        # Known ligature?
        if ch in LIGATURE_MAP:
            out.append(LIGATURE_MAP[ch])
        # PUA fallback — treat as 'tt'
        elif 0xE000 <= cp <= 0xF8FF:
            _SEEN_PUA_CHARS.add(ch)
            out.append("tt")
        # Zero-width / invisible — drop
        elif cp in (0x200B, 0x200C, 0x200D, 0xFEFF):
            continue
        else:
            out.append(ch)
    # Collapse runs of 3+ identical letters -> 2
    return re.sub(r'(.)\1{2,}', r'\1\1', "".join(out))


def debug_dump_pua_chars():
    """Call after scanning to see every PUA char that was hit."""
    if _SEEN_PUA_CHARS:
        print("=== PUA chars encountered (all mapped to 'tt') ===")
        for ch in sorted(_SEEN_PUA_CHARS, key=ord):
            print(f"  U+{ord(ch):04X}  repr={repr(ch)}")
    else:
        print("=== No PUA chars encountered ===")


def debug_find_ligature_char(photo_pdf_path, target_fragment="ma"):
    """
    Scans every word in the PDF and prints repr() for any word
    containing target_fragment (case-insensitive, after lowering).
    Example: target_fragment="ma" will catch "Matthew", "Mattie", etc.
    """
    import pdfplumber
    with pdfplumber.open(photo_pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages):
            for w in page.extract_words():
                if target_fragment in w['text'].lower():
                    print(f"  Page {page_num+1} | raw repr: {repr(w['text'])} | "
                          f"codepoints: {[f'U+{ord(c):04X}' for c in w['text']]}")
# ---------------------------------------------------------------------------


def extract_photos_geometric(photo_pdf_path, df):
    results = {}
    unmatched_data = []

    if not photo_pdf_path:
        return results, unmatched_data

    print(f"\n--- Starting Geometric Extraction: {os.path.basename(photo_pdf_path)} ---")

    # ------------------------------------------------------------------
    # 1. Prepare Student Data
    # ------------------------------------------------------------------
    student_map = {}
    
    # Debug counter
    total_students = 0

    for _, row in df.iterrows():
        s_last  = str(row[COLS['surname']]).strip().lower()
        s_first = str(row[COLS['first_name']]).strip().lower()
        s_id    = str(row[COLS['student_id']])
        s_roll  = str(row[COLS['rollgroup']]).strip().lower()

        # Clean the key the same way we'll clean PDF text:
        clean_key = clean_ligatures(
            s_last.replace(" ", "").replace("-", "").replace("'", "")
        )

        if clean_key not in student_map:
            student_map[clean_key] = []

        student_map[clean_key].append({
            "id":        s_id,
            "roll":      s_roll,
            "first":     s_first,
            "orig_last": s_last,
        })
        total_students += 1

    print(f"[DEBUG] Loaded {total_students} students ({len(student_map)} unique surnames).")

    # ------------------------------------------------------------------
    # 2. Constants
    # ------------------------------------------------------------------
    MAX_V_GAP        = 35    
    LOOKAHEAD_FENCE = 40    
    SAME_LINE_TOL    = 8     
    COL_PAD          = 30

    # ------------------------------------------------------------------
    # 3. Walk the PDF
    # ------------------------------------------------------------------
    with pdfplumber.open(photo_pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages):
            print(f"\n[DEBUG] Processing Page {page_num + 1}...")
            words  = page.extract_words()
            images = page.images
            claimed_images = set()

            print(f"[DEBUG] Found {len(words)} words and {len(images)} images on page.")

            # ----------------------------------------------------------
            # A. NAME MATCHING
            # ----------------------------------------------------------
            i = 0
            while i < len(words):
                words_skipped = 1

                for length in [5, 4, 3, 2, 1]:
                    if i + length > len(words):
                        continue

                    phrase_objs = words[i : i + length]

                    # SAME-LINE GUARD
                    tops = [w['top'] for w in phrase_objs]
                    if max(tops) - min(tops) > SAME_LINE_TOL:
                        continue

                    # Build key
                    raw_text = "".join(w['text'] for w in phrase_objs).lower()
                    text = clean_ligatures(raw_text)
                    text = text.replace(",", "").replace(":", "").replace(".", "").replace("-", "").replace("'", "")

                    if text not in student_map:
                        continue
                    
                    # --- FOUND A SURNAME MATCH ---
                    candidates = student_map[text]
                    
                    # Spatial bounds
                    surname_bottom = max(w['bottom'] for w in phrase_objs)
                    phrase_x0      = min(w['x0']      for w in phrase_objs)
                    phrase_x1      = max(w['x1']      for w in phrase_objs)
                    col_x0 = phrase_x0 - COL_PAD
                    col_x1 = phrase_x1 + COL_PAD

                    # SPATIALLY-FILTERED LOOKAHEAD
                    nearby_text_parts = []
                    for w_any in words:
                        if w_any['top'] < surname_bottom - 2: continue
                        if w_any['top'] > surname_bottom + LOOKAHEAD_FENCE: continue
                        if w_any['x1'] < col_x0 or w_any['x0'] > col_x1: continue
                        nearby_text_parts.append(clean_ligatures(w_any['text'].lower()))

                    nearby_text = " ".join(nearby_text_parts)

                    # PICK THE STUDENT
                    matched_student_id = None
                    disambiguation_method = "Single Match"

                    if len(candidates) == 1:
                        matched_student_id = candidates[0]['id']
                    else:
                        disambiguation_method = "First Name"
                        for cand in candidates:
                            if cand['first'] and cand['first'] in nearby_text:
                                matched_student_id = cand['id']
                                break

                        if matched_student_id is None:
                            disambiguation_method = "Roll Group"
                            for cand in candidates:
                                if cand['roll'] and cand['roll'] in nearby_text:
                                    matched_student_id = cand['id']
                                    break

                    if matched_student_id is None:
                        print(f"  [DEBUG] AMBIGUOUS: Found surname '{text}' but could not match First/Roll in nearby text: '{nearby_text}'")
                        continue
                    
                    print(f"  [DEBUG] MATCHED Name: '{text}' -> ID: {matched_student_id} (via {disambiguation_method})")

                    # GEOMETRY: Find photo
                    phrase_top = min(w['top'] for w in phrase_objs)
                    phrase_cx  = (phrase_x0 + phrase_x1) / 2

                    best_img_idx = None
                    best_img     = None
                    min_gap      = 9999

                    for img_idx, img in enumerate(images):
                        if img_idx in claimed_images: continue # Skip already taken
                        
                        img_bot = img['bottom']
                        if img_bot >= phrase_top: continue # Not above

                        gap = phrase_top - img_bot
                        if gap > MAX_V_GAP: 
                            # Debug log for rejection if it's kinda close but failed
                            if gap < MAX_V_GAP + 20:
                                print(f"    [Img {img_idx}] REJECTED: Too high (Gap {gap:.1f} > {MAX_V_GAP})")
                            continue

                        img_cx = (img['x0'] + img['x1']) / 2
                        h_dist = abs(img_cx - phrase_cx)
                        allowed_h_dist = (phrase_x1 - phrase_x0) / 2 + 40
                        
                        if h_dist > allowed_h_dist:
                            # Debug log for rejection if aligned vertically but off horizontally
                            print(f"    [Img {img_idx}] REJECTED: Off-center (Dist {h_dist:.1f} > {allowed_h_dist:.1f})")
                            continue

                        # If we get here, it's a valid candidate
                        if gap < min_gap:
                            min_gap      = gap
                            best_img     = img
                            best_img_idx = img_idx

                    if best_img:
                        print(f"    [Img {best_img_idx}] CLAIMED: Gap={min_gap:.1f}")
                        try:
                            claimed_images.add(best_img_idx)
                            bbox = (best_img['x0'], best_img['top'],
                                    best_img['x1'], best_img['bottom'])
                            crop   = page.within_bbox(bbox)
                            im_obj = crop.to_image(resolution=200).original
                            save_path = os.path.join(
                                TEMP_DIR, f"{matched_student_id}.jpg"
                            )
                            im_obj.save(save_path)
                            results[matched_student_id] = save_path
                        except Exception as e:
                            print(f"    [ERROR] Saving image: {e}")
                    else:
                        print(f"    [WARNING] No valid image found above '{text}' (Max Gap: {MAX_V_GAP})")

                    words_skipped = length
                    break 

                i += words_skipped

            # ----------------------------------------------------------
            # B. ORPHAN IMAGES
            # ----------------------------------------------------------
            for img_idx, img in enumerate(images):
                if img_idx in claimed_images:
                    continue
                try:
                    if (img['x1'] - img['x0']) < 30 or (img['bottom'] - img['top']) < 30:
                        continue

                    print(f"  [DEBUG] Orphan Image Found: Index {img_idx}")

                    bbox   = (img['x0'], img['top'], img['x1'], img['bottom'])
                    crop   = page.within_bbox(bbox)
                    im_obj = crop.to_image(resolution=200).original

                    unmatched_name = f"unmatched_p{page_num+1}_{img_idx}.jpg"
                    save_path      = os.path.join(TEMP_DIR, unmatched_name)
                    im_obj.save(save_path)

                    nearby_text = []
                    img_bottom  = img['bottom']
                    for w in words:
                        # Look BELOW the orphan
                        if img_bottom < w['top'] < (img_bottom + 50):
                            if (w['x0'] < img['x1']) and (w['x1'] > img['x0']):
                                nearby_text.append(clean_ligatures(w['text']))

                    found_text = " ".join(nearby_text) if nearby_text else "No text found immediately below"
                    print(f"    -> Text below orphan: {found_text}")

                    unmatched_data.append({
                        "path":       save_path,
                        "text_found": found_text,
                        "page":       page_num + 1,
                    })
                except Exception as e:
                    print(f"    [ERROR] Processing orphan {img_idx}: {e}")

    debug_dump_pua_chars()
    print(f"--- Finished. Extracted {len(results)} photos. ---\n")
    return results, unmatched_data


def image_to_a4_pdf(upload):
    """
    Converts an image upload to a standard A4 PDF page (595x842 points).
    Centers and scales the image to fit the page.
    """
    # Standard A4 size in PDF points (72 DPI equivalent)
    # This prevents the page from appearing huge in the PDF viewer
    A4_W, A4_H = 595, 842
    
    try:
        img = Image.open(upload)
        # Ensure correct color mode
        if img.mode != 'RGB':
            img = img.convert('RGB')
            
        # Calculate aspect ratio to 'contain' the image within A4
        width_ratio = A4_W / img.width
        height_ratio = A4_H / img.height
        scale = min(width_ratio, height_ratio)
        
        # New dimensions
        new_w = int(img.width * scale)
        new_h = int(img.height * scale)
            
        # Resize using high-quality resampling
        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        
        # Create a blank white A4 canvas
        canvas = Image.new('RGB', (A4_W, A4_H), (255, 255, 255))
        
        # Paste image in the center
        x_offset = (A4_W - new_w) // 2
        y_offset = (A4_H - new_h) // 2
        canvas.paste(img, (x_offset, y_offset))
        
        # Save as PDF bytes
        buf = BytesIO()
        canvas.save(buf, format="PDF", resolution=72)
        return buf.getvalue()
        
    except Exception as e:
        st.error(f"Error converting image to PDF: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# UI — Medical Booklet Creator
# ─────────────────────────────────────────────────────────────────────────────

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
  /* ── Hide Streamlit toolbar & kill the chin gap ── */
  [data-testid="stToolbar"],
  [data-testid="stDecoration"],
  #MainMenu,
  header { display: none !important; }
  [data-testid="stAppViewContainer"] > section > div:first-child { padding-top: 0 !important; }
  .block-container { padding-top: 0 !important; }

  /* ── Global background ── */
  [data-testid="stAppViewContainer"] { background: #f5f6fa; }
  [data-testid="stSidebar"] { display: none; }

  /* ── Tab styling ── */
  [data-testid="stTabs"] [role="tablist"] {
    gap: 4px;
    border-bottom: 2px solid #e2e5ee;
    padding-bottom: 0;
  }
  [data-testid="stTabs"] [role="tab"] {
    font-size: 0.85rem !important;
    font-weight: 500 !important;
    color: #6b6f82 !important;
    padding: 8px 18px !important;
    border-radius: 6px 6px 0 0 !important;
    border: none !important;
    background: transparent !important;
  }
  [data-testid="stTabs"] [role="tab"][aria-selected="true"] {
    color: #1a7f6e !important;
    border-bottom: 2px solid #1a7f6e !important;
    background: transparent !important;
  }

  /* ── Section headers ── */
  .section-head {
    font-size: 0.72rem;
    font-weight: 650;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #1a7f6e;
    margin: 28px 0 12px 0;
    padding-bottom: 8px;
    border-bottom: 2px solid #d0ede9;
  }

  /* ── Upload cards ── */
  .upload-card {
    background: #ffffff;
    border: 1px solid #e2e5ee;
    border-left: 4px solid #1a7f6e;
    border-radius: 10px;
    padding: 16px 18px;
    margin-bottom: 10px;
  }
  .upload-card.optional { border-left-color: #e8960a; }
  .upload-card-label { font-size: 0.82rem; font-weight: 600; color: #1a1d2e; margin-bottom: 4px; }
  .upload-card-desc { font-size: 0.76rem; color: #9295a8; margin-bottom: 10px; }
  .seqta-link {
    display: inline-flex; align-items: center; gap: 5px;
    font-size: 0.75rem; font-weight: 500; color: #1a7f6e;
    text-decoration: none; background: #e8f7f4;
    border: 1px solid #a8ddd6; border-radius: 5px;
    padding: 3px 9px; margin-bottom: 8px;
  }
  .seqta-link:hover { background: #d0ede9; }

  /* ── Options / step badges ── */
  .step-badge {
    display: inline-flex; align-items: center; justify-content: center;
    width: 24px; height: 24px; background: #1a7f6e; color: white;
    border-radius: 50%; font-size: 0.75rem; font-weight: 650;
    margin-right: 8px; flex-shrink: 0;
  }
  .step-row { display: flex; align-items: center; margin-bottom: 6px; }
  .step-label { font-size: 0.95rem; font-weight: 600; color: #1a1d2e; }
  .options-card {
    background: #ffffff; border: 1px solid #e2e5ee;
    border-radius: 10px; padding: 18px 20px; margin-bottom: 12px;
  }
  .options-card-title {
    font-size: 0.8rem; font-weight: 650; color: #1a7f6e;
    text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 10px;
  }

  /* ── Footer ── */
  .mbc-footer {
    margin-top: 48px; padding-top: 16px;
    border-top: 1px solid #e2e5ee; text-align: center;
    font-size: 0.75rem; color: #b0b3c4;
  }

  /* ── Streamlit overrides ── */
  [data-testid="stFileUploader"] { background: #fafcfb; border-radius: 8px; }
  div[data-testid="stCheckbox"] label { font-size: 0.88rem !important; }
  div[data-testid="stSelectbox"] label { font-size: 0.88rem !important; }
  .stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #1a7f6e, #2563a8) !important;
    border: none !important; border-radius: 8px !important;
    font-weight: 600 !important; padding: 10px 28px !important;
    font-size: 0.9rem !important; color: #ffffff !important;
  }
  .stButton > button[kind="primary"]:hover { opacity: 0.92 !important; }
  .stButton > button:not([kind="primary"]) { border-radius: 7px !important; font-size: 0.86rem !important; }
  [data-testid="stTextInput"] input {
    border-radius: 8px !important; font-size: 0.9rem !important; border-color: #d0ede9 !important;
  }
  [data-testid="stTextInput"] input:focus {
    border-color: #1a7f6e !important; box-shadow: 0 0 0 2px rgba(26,127,110,0.15) !important;
  }
  div.stAlert { border-radius: 8px !important; font-size: 0.85rem !important; }
  [data-testid="stProgress"] > div > div {
    background: linear-gradient(90deg, #1a7f6e, #2563a8) !important;
  }
</style>
""", unsafe_allow_html=True)

# ── Header + Menu ─────────────────────────────────────────────────────────────
# Strategy: paint the page top with a CSS body::before gradient band.
# The Streamlit columns row sits ON TOP of it with a negative top margin
# to pull it up into the painted area. Zero React issues, zero div injection.


# ── Sticky header: columns row that sticks to top on scroll ─────────────────
# `position: sticky` works within Streamlit's layout flow — no fighting the
# layout engine, no chin gap, no scroll-away. The gradient is on the row itself.

st.markdown("""
<style>
  /* ── Make the very first horizontal block sticky ── */
  [data-testid="stMainBlockContainer"] > div > [data-testid="stVerticalBlock"]
    > [data-testid="stVerticalBlockBorderWrapper"]:first-child {
    position: sticky !important;
    top: 0 !important;
    z-index: 999 !important;
  }
  [data-testid="stMainBlockContainer"] > div > [data-testid="stVerticalBlock"]
    > [data-testid="stVerticalBlockBorderWrapper"]:first-child > div {
    background: linear-gradient(135deg, #1a7f6e 0%, #2563a8 100%) !important;
    padding: 12px 24px !important;
    margin: -4rem -4rem 0 -4rem !important;
  }
  /* Text in the title column */
  [data-testid="stMainBlockContainer"] > div > [data-testid="stVerticalBlock"]
    > [data-testid="stVerticalBlockBorderWrapper"]:first-child p {
    color: #ffffff !important;
    margin: 0 !important;
    line-height: 1.3 !important;
  }
  /* Caption under title */
  [data-testid="stMainBlockContainer"] > div > [data-testid="stVerticalBlock"]
    > [data-testid="stVerticalBlockBorderWrapper"]:first-child
      [data-testid="stCaptionContainer"] p {
    color: rgba(255,255,255,0.55) !important;
    font-size: 0.72rem !important;
    font-weight: 400 !important;
    text-transform: none !important;
    letter-spacing: 0 !important;
  }
  /* ⋯ popover button ghost style */
  [data-testid="stMainBlockContainer"] > div > [data-testid="stVerticalBlock"]
    > [data-testid="stVerticalBlockBorderWrapper"]:first-child
      [data-testid="stPopover"] > button {
    background: rgba(255,255,255,0.15) !important;
    border: 1px solid rgba(255,255,255,0.32) !important;
    color: #ffffff !important;
    border-radius: 7px !important;
    font-size: 1rem !important;
    padding: 6px 12px !important;
    min-height: unset !important;
    line-height: 1 !important;
    float: right !important;
  }
  [data-testid="stMainBlockContainer"] > div > [data-testid="stVerticalBlock"]
    > [data-testid="stVerticalBlockBorderWrapper"]:first-child
      [data-testid="stPopover"] > button:hover {
    background: rgba(255,255,255,0.26) !important;
  }

  /* ── Popover dropdown panel ── */
  [data-testid="stPopoverBody"] {
    padding: 6px 0 10px !important;
    min-width: 195px !important;
  }
  /* Section label */
  [data-testid="stPopoverBody"] [data-testid="stMarkdownContainer"] p {
    font-size: 0.67rem !important;
    font-weight: 700 !important;
    letter-spacing: 0.09em !important;
    text-transform: uppercase !important;
    color: #9295a8 !important;
    padding: 10px 14px 3px 14px !important;
    margin: 0 !important;
    line-height: 1 !important;
  }
  /* Action buttons */
  [data-testid="stPopoverBody"] [data-testid="stButton"] > button {
    all: unset !important;
    display: flex !important;
    align-items: center !important;
    width: 100% !important;
    padding: 9px 14px !important;
    font-size: 0.88rem !important;
    font-weight: 500 !important;
    color: #1a1d2e !important;
    cursor: pointer !important;
    box-sizing: border-box !important;
    line-height: 1.2 !important;
  }
  [data-testid="stPopoverBody"] [data-testid="stButton"] > button:hover {
    background: #f2f3f7 !important;
    color: #1a7f6e !important;
  }
  /* Divider */
  [data-testid="stPopoverBody"] hr {
    margin: 5px 0 !important;
    border: none !important;
    border-top: 1px solid #ecedf2 !important;
  }
  /* Caption */
  [data-testid="stPopoverBody"] [data-testid="stCaptionContainer"] {
    padding: 6px 14px 2px !important;
    color: #9295a8 !important;
    font-size: 0.76rem !important;
    line-height: 1.55 !important;
  }
</style>
""", unsafe_allow_html=True)

_h1, _h2 = st.columns([11, 1])
with _h1:
    st.markdown("**📋 Medical Booklet Creator**")
    st.caption("Created by Thomas van Sant")
with _h2:
    with st.popover("•••"):
        st.markdown("Actions")
        if st.button("↩  Start Over", use_container_width=True):
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            st.rerun()
        if st.button("⏹  Close the App", use_container_width=True):
            st.session_state._show_close = not st.session_state.get("_show_close", False)
            st.rerun()
        st.divider()
        st.markdown("Info")
        if st.button("❓  Help", use_container_width=True):
            st.session_state._show_help = not st.session_state.get("_show_help", False)
            st.rerun()
        if st.button("ℹ  About", use_container_width=True):
            st.session_state._show_about = not st.session_state.get("_show_about", False)
            st.rerun()

if st.session_state.get("_show_close"):
    st.info("**To close the app:** Switch to the Terminal window that opened when you launched, press **Ctrl + C**, then close Terminal.", icon="⏹")

if st.session_state.get("_show_help"):
    with st.container(border=True):
        st.markdown("**Quick help**")
        st.markdown("""
- **Launch:** Double-click **Open Medical Booklet.command** in `Documents/medical-booklet`, or click it in your Dock.
- **Stop the app:** Find the Terminal window and press **Ctrl + C**.
- **Seqta data:** Both required files come from [Seqta Reporting](https://teach.friends.tas.edu.au/studentSummary/reporting).
- **Start fresh:** Use **Start Over** in the ••• menu to clear all uploads and begin again.
        """)
        if st.button("✕  Close help"):
            st.session_state._show_help = False
            st.rerun()

if st.session_state.get("_show_about"):
    with st.container(border=True):
        st.markdown("**📋 Medical Booklet Creator**")
        st.markdown("Generates student profile PDFs for excursion and field activity planning — medical information, emergency contacts, learning support, swimming ability and dietary requirements.")
        st.caption("Created by Thomas van Sant · Friends' School")
        if st.button("✕  Close"):
            st.session_state._show_about = False
            st.rerun()


SEQTA_URL = "https://teach.friends.tas.edu.au/studentSummary/reporting"

if "attachments" not in st.session_state: st.session_state.attachments = {}
if "project_title" not in st.session_state: st.session_state.project_title = ""

t1, t2 = st.tabs(["  Setup  ", "  Process & Generate  "])

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1 — SETUP
# ═══════════════════════════════════════════════════════════════════════════════
with t1:

    st.session_state.project_title = st.text_input(
        "Booklet title",
        st.session_state.project_title,
        placeholder="e.g. Year 9 Camp — March 2025"
    )

    # ── Required documents ────────────────────────────────────────────────────
    st.markdown('<div class="section-head">Required — from Seqta</div>', unsafe_allow_html=True)

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown(f"""
        <div class="upload-card">
          <div class="upload-card-label">Student List CSV</div>
          <div class="upload-card-desc">Student data including medical, emergency and learning information.</div>
          <a class="seqta-link" href="{SEQTA_URL}" target="_blank">↗ Open in Seqta</a>
        </div>
        """, unsafe_allow_html=True)
        csv = st.file_uploader("Student List CSV", type="csv", label_visibility="collapsed")

    with col_b:
        st.markdown(f"""
        <div class="upload-card">
          <div class="upload-card-label">Student Photos PDF</div>
          <div class="upload-card-desc">Photo contact sheet exported from Seqta.</div>
          <a class="seqta-link" href="{SEQTA_URL}" target="_blank">↗ Open in Seqta</a>
        </div>
        """, unsafe_allow_html=True)
        photos = st.file_uploader("Student Photos PDF", type="pdf", label_visibility="collapsed")

    # ── Optional documents ────────────────────────────────────────────────────
    st.markdown('<div class="section-head">Optional — from Paperly forms</div>', unsafe_allow_html=True)

    col_c, col_d, col_e = st.columns(3)
    with col_c:
        st.markdown("""
        <div class="upload-card optional">
          <div class="upload-card-label">Attendance CSV</div>
          <div class="upload-card-desc">Adds home contacts and addresses to each profile.</div>
        </div>
        """, unsafe_allow_html=True)
        contact_csv = st.file_uploader("Attendance CSV", type="csv", label_visibility="collapsed")

    with col_d:
        st.markdown("""
        <div class="upload-card optional">
          <div class="upload-card-label">Swimming Ability CSV</div>
          <div class="upload-card-desc">Adds swimming competency to each student profile.</div>
        </div>
        """, unsafe_allow_html=True)
        swimming_csv = st.file_uploader("Swimming Ability CSV", type="csv", label_visibility="collapsed")

    with col_e:
        st.markdown("""
        <div class="upload-card optional">
          <div class="upload-card-label">Dietary Requirements CSV</div>
          <div class="upload-card-desc">Adds dietary needs and generates a summary table.</div>
        </div>
        """, unsafe_allow_html=True)
        dietary_csv = st.file_uploader("Dietary Requirements CSV", type="csv", label_visibility="collapsed")

    # ── File processing (logic unchanged) ─────────────────────────────────────
    if csv:
        df_temp = pd.read_csv(csv).fillna("")
        if contact_csv:
            try:
                contact_df = pd.read_csv(contact_csv).fillna("")
                st.session_state.contact_csv_df = contact_df
                c_map = CONFIG.get('contact_file_mappings', {})
                id_col = COLS['student_id']
                join_key = c_map.get('join_key', 'ID')
                df_temp[id_col] = df_temp[id_col].astype(str).str.strip()
                contact_df[join_key] = contact_df[join_key].astype(str).str.strip()
                contact_cols_needed = [
                    join_key,
                    c_map.get('sc1_name_pref', 'SC1 Preferred'),
                    c_map.get('sc1_name_sur', 'SC1 Surname'),
                    c_map.get('sc1_mobile', 'SC1 Mobile'),
                    c_map.get('sc2_name_pref', 'SC2 Preferred'),
                    c_map.get('sc2_name_sur', 'SC2 Surname'),
                    c_map.get('sc2_mobile', 'SC2 Mobile'),
                    c_map.get('address', 'Contact Address'),
                    c_map.get('home_phone', 'Home Phone')
                ]
                contact_cols_to_merge = [col for col in contact_cols_needed if col in contact_df.columns]
                contact_df_subset = contact_df[contact_cols_to_merge]
                df_temp = pd.merge(df_temp, contact_df_subset, left_on=id_col, right_on=join_key, how='left')
                print(f"\n=== CONTACT MERGE DEBUG ===")
                print(f"Columns after merge: {list(df_temp.columns)}")
                print(f"Looking for: SC1 Preferred, SC1 Surname, SC2 Preferred, SC2 Surname")
                st.success(f"✅ Merged contacts for {len(contact_df)} students")
            except Exception as e:
                st.error(f"Error merging contacts: {e}")
        st.session_state.df = df_temp
        st.session_state.df_final = st.session_state.df
        st.success("✅ Student list loaded")

    if swimming_csv:
        st.session_state.swimming_csv = swimming_csv
        st.success("✅ Swimming ability CSV loaded")

    if dietary_csv:
        st.session_state.dietary_csv = dietary_csv
        st.success("✅ Dietary requirements CSV loaded")

    if photos:
        path = os.path.join(TEMP_DIR, "photos.pdf")
        with open(path, "wb") as f: f.write(photos.getbuffer())
        st.session_state.photo_pdf = path
        st.success("✅ Photos loaded")

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2 — PROCESS & GENERATE
# ═══════════════════════════════════════════════════════════════════════════════
with t2:

    if "df_final" not in st.session_state or "photo_pdf" not in st.session_state:
        st.info("Upload a Student List CSV and Photos PDF in the Setup tab first.")
        st.stop()

    df_final = st.session_state.df_final
    photo_pdf_path = st.session_state.photo_pdf

    # ── Step 1: Analyse ───────────────────────────────────────────────────────
    st.markdown('<div class="section-head">Step 1 — Analyse photos</div>', unsafe_allow_html=True)

    if st.button("Scan & Match Photos", type="primary"):
        with st.spinner("Scanning PDF and matching photos to students…"):
            results, unmatched = extract_photos_geometric(photo_pdf_path, df_final)
            st.session_state.auto_matches = results
            st.session_state.unmatched_data = unmatched
            st.session_state.extraction_done = True
            st.session_state.manual_selections = {}
            st.session_state.detected_plans = detect_medical_plans(df_final)

            if 'swimming_csv' in st.session_state:
                contact_data = st.session_state.get('contact_csv_df', None)
                swim_matched, swim_unmatched = match_swimming_ability(df_final, st.session_state.swimming_csv, contact_data)
                st.session_state.swimming_matched = swim_matched
                st.session_state.swimming_unmatched = swim_unmatched
                st.session_state.swimming_manual_selections = {}

            if 'dietary_csv' in st.session_state:
                dietary_matched, dietary_unmatched = match_dietary_requirements(df_final, st.session_state.dietary_csv)
                st.session_state.dietary_matched = dietary_matched
                st.session_state.dietary_unmatched = dietary_unmatched
                st.session_state.dietary_manual_selections = {}

            st.rerun()

    if st.session_state.get("extraction_done", False):

        # ── Step 2: Review photos ─────────────────────────────────────────────
        st.markdown('<div class="section-head">Step 2 — Review matches</div>', unsafe_allow_html=True)

        student_options = ["(Skip)"]
        name_to_id_map = {}
        id_to_name_map = {}
        for _, row in df_final.iterrows():
            sid = str(row[COLS['student_id']])
            label = f"{row[COLS['surname']]}, {row[COLS['first_name']]} ({sid})"
            student_options.append(label)
            name_to_id_map[label] = sid
            id_to_name_map[sid] = f"{row[COLS['first_name']]} {row[COLS['surname']]}"

        # Photos
        n_auto = len(st.session_state.auto_matches)
        n_unmatched = len(st.session_state.unmatched_data)
        if n_unmatched > 0:
            with st.expander(f"⚠️  {n_unmatched} photos need manual matching  ({n_auto} matched automatically)", expanded=True):
                for item in st.session_state.unmatched_data:
                    c1, c2 = st.columns([1, 4])
                    with c1: st.image(item['path'], width=90)
                    with c2:
                        st.caption(f"Page {item['page']} · Text nearby: *{item['text_found']}*")
                        sel = st.selectbox("Assign to student:", options=student_options, key=f"select_{item['path']}")
                        if sel != "(Skip)":
                            st.session_state.manual_selections[item['path']] = name_to_id_map[sel]
                        elif item['path'] in st.session_state.manual_selections:
                            del st.session_state.manual_selections[item['path']]
                    st.divider()
        else:
            st.success(f"✅ All {n_auto} photos matched automatically")

        # Swimming
        if 'swimming_csv' in st.session_state:
            total_swim_matched = len(st.session_state.get('swimming_matched', {}))
            total_swim_unmatched = len(st.session_state.get('swimming_unmatched', []))
            if total_swim_unmatched > 0:
                with st.expander(f"⚠️  {total_swim_unmatched} swimming records need manual matching", expanded=True):
                    st.caption("These records couldn't be matched automatically — please assign them below.")
                    for item in st.session_state.swimming_unmatched:
                        c1, c2 = st.columns([1, 3])
                        with c1:
                            st.markdown(f"**{item['student_name']}**")
                        with c2:
                            color_map = {'swim-cannot': '🔴', 'swim-weak': '🟠', 'swim-ok': '🟢', 'swim-none': '⚪'}
                            ability_color = get_swimming_display_color(item['ability'])
                            st.markdown(f"{color_map.get(ability_color, '⚪')} {item['ability']}")
                            sel = st.selectbox("Assign to student:", options=student_options, key=f"swim_select_{item['index']}")
                            if sel != "(Skip)":
                                st.session_state.swimming_manual_selections[item['index']] = name_to_id_map[sel]
                            elif item['index'] in st.session_state.swimming_manual_selections:
                                del st.session_state.swimming_manual_selections[item['index']]
                        st.divider()
            else:
                st.success(f"✅ All {total_swim_matched} swimming records matched automatically")

        # Dietary
        if 'dietary_csv' in st.session_state:
            total_diet_matched = len(st.session_state.get('dietary_matched', {}))
            total_diet_unmatched = len(st.session_state.get('dietary_unmatched', []))
            if total_diet_unmatched > 0:
                with st.expander(f"⚠️  {total_diet_unmatched} dietary records need manual matching", expanded=True):
                    st.caption("These records couldn't be matched automatically — please assign them below.")
                    for item in st.session_state.dietary_unmatched:
                        c1, c2 = st.columns([1, 3])
                        with c1:
                            st.markdown(f"**{item['student_name']}**")
                        with c2:
                            preview = item['dietary_req'][:100] + "…" if len(item['dietary_req']) > 100 else item['dietary_req']
                            st.markdown(f"🍽️ {preview}")
                            sel = st.selectbox("Assign to student:", options=student_options, key=f"dietary_select_{item['index']}")
                            if sel != "(Skip)":
                                st.session_state.dietary_manual_selections[item['index']] = name_to_id_map[sel]
                            elif item['index'] in st.session_state.dietary_manual_selections:
                                del st.session_state.dietary_manual_selections[item['index']]
                        st.divider()
            else:
                st.success(f"✅ All {total_diet_matched} dietary records matched automatically")

        # ── Step 3: Medical plans ─────────────────────────────────────────────
        st.markdown('<div class="section-head">Step 3 — Medical action plans</div>', unsafe_allow_html=True)

        detected = st.session_state.get('detected_plans', {})
        if detected:
            for sid, plans in detected.items():
                s_name = id_to_name_map.get(sid, sid)
                with st.container():
                    st.markdown(f"**{s_name}**")
                    for p_idx, plan in enumerate(plans):
                        col1, col2 = st.columns([3, 2])
                        with col1:
                            st.markdown(f"**{plan['condition']}**")
                            if plan.get('url'): st.markdown(f"[↗ Open document]({plan['url']})")
                        with col2:
                            st.file_uploader(f"Upload {plan['condition']}", type=['pdf','png','jpg'], key=f"plan_upload_{sid}_{p_idx}")
                    st.divider()
        else:
            st.caption("No action plans detected in student data.")

        with st.expander("Add a plan manually"):
            st.caption("Select a student and upload a file. Add right before generating.")
            man_sel = st.selectbox("Select student", sorted(list(name_to_id_map.keys()))[1:])
            st.file_uploader("Upload file", type=['pdf','png','jpg'], key="manual_plan_file")

        # ── Step 4: Content options ───────────────────────────────────────────
        st.markdown('<div class="section-head">Step 4 — Content options</div>', unsafe_allow_html=True)

        col1, col2 = st.columns(2)
        with col1:
            st.markdown('<div class="options-card-title">Header details</div>', unsafe_allow_html=True)
            opt_year  = st.checkbox("Year level",    value=True)
            opt_roll  = st.checkbox("Roll group",    value=True)
            opt_house = st.checkbox("House",         value=True)
            opt_dob   = st.checkbox("Date of birth", value=True)
            opt_tutor = st.checkbox("Tutor",         value=True)
            opt_sid   = st.checkbox("Student ID",    value=True)

            has_swimming     = 'swimming_csv' in st.session_state
            has_dietary      = 'dietary_csv' in st.session_state
            has_contact_csv  = 'contact_csv_df' in st.session_state

            if has_swimming or has_dietary or has_contact_csv:
                st.markdown("---")
                st.markdown('<div class="options-card-title">Additional data</div>', unsafe_allow_html=True)
            opt_swimming = st.checkbox("Swimming ability",      value=True) if has_swimming else False
            opt_dietary  = st.checkbox("Dietary requirements",  value=True) if has_dietary  else False
            opt_sec_home = st.checkbox("Home contacts",         value=True) if has_contact_csv else False

        with col2:
            st.markdown('<div class="options-card-title">Profile sections</div>', unsafe_allow_html=True)
            opt_sec_med   = st.checkbox("Medical information",         value=True)
            opt_sec_emerg = st.checkbox("Emergency contacts",          value=True)
            opt_sec_docs  = st.checkbox("Medical contacts (doctors)",  value=True)
            opt_sec_learn = st.checkbox("Learning & support",          value=True)

        # ── Step 5: Sort & output ─────────────────────────────────────────────
        st.markdown('<div class="section-head">Step 5 — Sort & output</div>', unsafe_allow_html=True)

        col3, col4 = st.columns(2)
        with col3:
            sort_by = st.selectbox("Sort students by:", ["Alphabetical (Surname)", "Roll Group", "House", "Year Level"])
        with col4:
            if sort_by == "Alphabetical (Surname)":
                output_mode = "Single Document"
                st.caption("Alphabetical sorting produces a single combined document.")
            else:
                output_mode = st.radio("Output:", ["Single Document", f"Split by {sort_by}"])

        st.markdown("")

        if st.button("Generate Medical Booklet", type="primary"):

            # ── Gather plans (logic unchanged) ───────────────────────────────
            plan_map = {}
            detected = st.session_state.get('detected_plans', {})
            if detected:
                for sid, plans in detected.items():
                    for idx, _ in enumerate(plans):
                        k = f"plan_upload_{sid}_{idx}"
                        f = st.session_state.get(k)
                        if f:
                            if sid not in plan_map: plan_map[sid] = []
                            if f not in plan_map[sid]: plan_map[sid].append(f)

            if "medical_plan_files" in st.session_state:
                for sid, fl in st.session_state.medical_plan_files.items():
                    if sid not in plan_map: plan_map[sid] = []
                    for f in fl:
                        if f not in plan_map[sid]: plan_map[sid].append(f)

            if st.session_state.get("manual_plan_file") and "man_sel" in locals() and man_sel:
                msid = name_to_id_map[man_sel]
                mf = st.session_state.get("manual_plan_file")
                if msid not in plan_map: plan_map[msid] = []
                if mf not in plan_map[msid]: plan_map[msid].append(mf)

            # ── Prepare data maps (logic unchanged) ──────────────────────────
            final_photo_map = st.session_state.auto_matches.copy()
            for p, s in st.session_state.manual_selections.items(): final_photo_map[s] = p

            final_swimming_map = st.session_state.get('swimming_matched', {}).copy()
            if st.session_state.get('swimming_manual_selections'):
                for swim_idx, student_id in st.session_state.swimming_manual_selections.items():
                    for item in st.session_state.swimming_unmatched:
                        if item['index'] == swim_idx:
                            final_swimming_map[student_id] = item['ability']
                            break

            final_dietary_map = st.session_state.get('dietary_matched', {}).copy()
            if st.session_state.get('dietary_manual_selections'):
                for dietary_idx, student_id in st.session_state.dietary_manual_selections.items():
                    for item in st.session_state.dietary_unmatched:
                        if item['index'] == dietary_idx:
                            final_dietary_map[student_id] = item['dietary_req']
                            break

            print(f"\n{'='*80}")
            print("SWIMMING ABILITY MAP FOR PDF GENERATION")
            print(f"{'='*80}")
            print(f"Total students with swimming data: {len(final_swimming_map)}")
            if final_swimming_map:
                print("\nFirst 10 students with swimming ability:")
                for idx, (sid, ability) in enumerate(list(final_swimming_map.items())[:10]):
                    print(f"  Student {sid}: {ability}")
            else:
                print("⚠️  WARNING: No swimming abilities found!")
                print("   Check that swimming CSV was uploaded and analyzed")
            print(f"{'='*80}\n")

            # ── Render (logic unchanged) ──────────────────────────────────────
            status = st.status("Generating booklet…", expanded=True)
            env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))
            tpl = env.get_template("profiles.html")
            display_opts = {
                "year": opt_year, "roll": opt_roll, "house": opt_house,
                "dob": opt_dob, "tutor": opt_tutor, "sid": opt_sid,
                "swimming": opt_swimming, "dietary": opt_dietary
            }

            all_records = []
            total = len(df_final)
            prog = st.progress(0)

            for idx, (_, r) in enumerate(df_final.iterrows()):
                prog.progress((idx+1)/total)
                sid = str(r[COLS['student_id']])
                link_id = re.sub(r'[^a-zA-Z0-9]', '', sid) or f"row{idx}"

                fname, sname = r[COLS['first_name']], r[COLS['surname']]
                dob = str(r.get('Birth date', r.get('Birth Date', ''))).strip()
                try: dob = datetime.strptime(dob, '%Y-%m-%d').strftime('%d %b %Y')
                except: pass
                house = str(r.get(COLS.get('house', 'House'), '')).strip()
                tutor = parse_tutor(str(r.get(COLS.get('general_notes', 'General notes'), '')))
                year_lvl = str(r[COLS['year']])
                roll = str(r[COLS['rollgroup']])

                raw_med   = str(r.get(COLS['medical_notes'], ""))
                raw_emerg = str(r.get(COLS['emergency_notes'], ""))
                parsed_med  = parse_medical_text(raw_med)
                parsed_con  = parse_emergency_contacts(raw_emerg)
                parsed_home = parse_home_contacts(r)

                sections = []
                layout = CONFIG["default_profile_layout"]
                for sec in layout:
                    is_med = COLS['medical_notes'] in sec['fields']
                    is_emg = COLS['emergency_notes'] in sec['fields']
                    is_lrn = COLS['special_notes'] in sec['fields']
                    if is_med and opt_sec_med:
                        sections.append({"title": sec['section'], "type": "medical_cards", "content": parsed_med})
                    elif is_emg:
                        if opt_sec_home and (parsed_home['contacts'] or parsed_home['home_address'] or parsed_home['home_phone']):
                            sections.append({"title": "Home Contacts", "type": "home_contacts", "content": parsed_home})
                        if opt_sec_emerg:
                            sections.append({"title": sec['section'], "type": "emergency_grid", "content": parsed_con})
                        if opt_sec_docs:
                            d_col = "Doctor notes" if "Doctor notes" in r else COLS.get('doctor_details')
                            if d_col and d_col in r:
                                sections.append({"title": "Medical Contacts", "type": "doctor_grid", "content": parse_doctors(str(r.get(d_col, "")))})
                    elif is_lrn and opt_sec_learn:
                        sections.append({"title": sec['section'], "type": "learning_support", "content": parse_learning_support(str(r.get(COLS['special_notes'], "")))})
                    elif not (is_med or is_emg or is_lrn):
                        vals = [str(r.get(f,"")).strip() for f in sec['fields'] if str(r.get(f,"")).strip()]
                        if not vals: vals = ["No data supplied."]
                        sections.append({"title": sec['section'], "type": "text", "content": vals})

                embedded = []
                if sid in plan_map:
                    for f in plan_map[sid]: embedded.extend(convert_file_to_images(f))
                if sid in st.session_state.attachments:
                    for f in st.session_state.attachments[sid]: embedded.extend(convert_file_to_images(f))

                med_l = raw_med.lower()
                c_disp = f"{parsed_con[0]['name']} ({parsed_con[0]['phone']['display']})" if parsed_con else ""

                swim_ability = final_swimming_map.get(sid, "Data not recorded")
                swim_color   = get_swimming_display_color(swim_ability)
                dietary_req  = final_dietary_map.get(sid, "No data given")

                profile_obj = {
                    "id": sid, "link_id": link_id, "first": fname, "last": sname,
                    "year": year_lvl, "roll": roll, "house": house, "dob": dob, "tutor": tutor,
                    "swimming": swim_ability, "swim_color": swim_color,
                    "dietary": dietary_req,
                    "photo": img_to_base64(final_photo_map.get(sid)),
                    "sections": sections, "attachments": embedded
                }
                matrix_obj = {
                    "id": sid, "link_id": link_id, "name": f"{sname}, {fname}",
                    "contact": c_disp, "asthma": "asthma" in med_l,
                    "allergy": "allergy" in med_l, "anaphylaxis": "anaphylaxis" in med_l,
                    "swimming": swim_ability, "swim_color": swim_color
                }
                medical_obj = None
                if parsed_med:
                    medical_obj = {"name": f"{fname} {sname}", "link_id": link_id, "conditions": parsed_med}

                all_records.append({
                    "profile": profile_obj, "matrix": matrix_obj, "medical": medical_obj,
                    "sort_keys": {"alpha": sname + fname, "roll": roll, "house": house, "year": year_lvl}
                })

            # ── Sort & group (logic unchanged) ────────────────────────────────
            status.write("Sorting & grouping…")

            def render_subset(records, title_suffix=""):
                s_list   = [r['profile'] for r in records]
                m_list   = [r['matrix']  for r in records]
                med_list = [r['medical'] for r in records if r['medical']]
                m_list.sort(key=lambda x: x['name'])
                full_html = tpl.render(
                    title=f"{st.session_state.project_title} {title_suffix}",
                    date=datetime.now().strftime("%d %B %Y"),
                    students=s_list, matrix=m_list, medical_full=med_list,
                    options=display_opts, mode="full"
                )
                return HTML(string=full_html).write_pdf()

            if sort_by == "Roll Group":
                all_records.sort(key=lambda x: (str(x['sort_keys']['roll']), x['sort_keys']['alpha']))
                group_key = 'roll'
            elif sort_by == "House":
                all_records.sort(key=lambda x: (str(x['sort_keys']['house']), x['sort_keys']['alpha']))
                group_key = 'house'
            elif sort_by == "Year Level":
                all_records.sort(key=lambda x: (str(x['sort_keys']['year']), x['sort_keys']['alpha']))
                group_key = 'year'
            else:
                all_records.sort(key=lambda x: x['sort_keys']['alpha'])
                group_key = 'alpha'

            if "Split" in output_mode:
                status.write("Generating split PDFs…")
                zip_buffer = BytesIO()
                groups = {}
                for r in all_records:
                    k = r['sort_keys'][group_key]
                    if not k: k = "Unknown"
                    if k not in groups: groups[k] = []
                    groups[k].append(r)
                with zipfile.ZipFile(zip_buffer, "w") as zf:
                    for g_name, g_records in groups.items():
                        safe_name = re.sub(r'[^a-zA-Z0-9]', '_', str(g_name))
                        pdf_data = render_subset(g_records, title_suffix=f"— {g_name}")
                        zf.writestr(f"Medical_Booklet_{safe_name}.pdf", pdf_data)
                status.update(label="✅ All files generated", state="complete", expanded=False)
                st.download_button("⬇ Download ZIP", data=zip_buffer.getvalue(),
                                   file_name="Medical_Booklets.zip", mime="application/zip")
            else:
                status.write("Generating PDF…")
                pdf_data = render_subset(all_records)
                status.update(label="✅ Booklet ready", state="complete", expanded=False)
                st.download_button("⬇ Download Medical Booklet", data=pdf_data,
                                   file_name="Medical_Booklet.pdf", mime="application/pdf")

# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="mbc-footer">
  Medical Booklet Creator &nbsp;·&nbsp; Created by Thomas van Sant
</div>
""", unsafe_allow_html=True)
