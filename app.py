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
if 'photo_permissions_map' not in st.session_state:
    st.session_state.photo_permissions_map = {} # Stores { 'student_id': 'Yes'|'No'|'No Response' }
if 'active_feature' not in st.session_state:
    st.session_state.active_feature = None  # None | 'booklet' | 'group'
if 'group_results' not in st.session_state:
    st.session_state.group_results = None  # Stores last group creator results
if 'group_email_input' not in st.session_state:
    st.session_state.group_email_input = ""
if 'seqta_contact_matched' not in st.session_state:
    st.session_state.seqta_contact_matched = {}
if 'seqta_contact_unmatched' not in st.session_state:
    st.session_state.seqta_contact_unmatched = []
if 'seqta_contact_manual' not in st.session_state:
    st.session_state.seqta_contact_manual = {}
import pandas as pd
import zipfile
import yaml
import urllib.parse
import re
import base64
import pdfplumber
import unicodedata
import requests
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
    page_title="Medical Booklet Tools",
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
    Uses magic byte sniffing to detect file type reliably — never relies solely
    on the .name extension, which may be absent or wrong for BytesIO/UploadedFile.
    """
    images_b64 = []
    try:
        file_obj.seek(0)
        file_bytes = file_obj.read()

        if not file_bytes:
            return []

        file_buffer = BytesIO(file_bytes)
        fname = getattr(file_obj, 'name', '') or ''

        # Detect type by magic bytes first, then fall back to extension
        is_pdf = file_bytes[:4] == b'%PDF'
        is_png = file_bytes[:4] == b'\x89PNG'
        is_jpg = file_bytes[:3] == b'\xff\xd8\xff'
        name_says_pdf = fname.lower().endswith('.pdf')

        # Attachment compression settings:
        # 150 DPI and JPEG quality 72 give a good size/quality balance for
        # action plan documents. Max dimension cap prevents oversized scans
        # from inflating the PDF further.
        ATTACH_DPI     = 150
        ATTACH_QUALITY = 72
        ATTACH_MAX_PX  = 2000  # longest edge cap in pixels

        def _compress_img(im):
            """Resize if oversized, then return compressed JPEG bytes."""
            im = im.convert("RGB")
            w, h = im.size
            if max(w, h) > ATTACH_MAX_PX:
                scale = ATTACH_MAX_PX / max(w, h)
                im = im.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
            buf = BytesIO()
            im.save(buf, format="JPEG", quality=ATTACH_QUALITY, optimize=True)
            return base64.b64encode(buf.getvalue()).decode()

        if is_pdf or (name_says_pdf and not is_png and not is_jpg):
            with pdfplumber.open(file_buffer) as pdf:
                for page in pdf.pages:
                    im = page.to_image(resolution=ATTACH_DPI).original
                    images_b64.append(_compress_img(im))
        else:
            img = Image.open(file_buffer)
            images_b64.append(_compress_img(img))


    except Exception as e:
        fname = getattr(file_obj, 'name', 'unknown')

    return images_b64

def auto_download_plan(url, session_cookie, cookie_name="ASP.NET_SessionId"):
    """
    Attempts to download a medical action plan file from a URL using a session cookie.
    Returns: (BytesIO file object, filename, error_message)
    - On success: (BytesIO, "filename.pdf", None)
    - On failure: (None, None, "error description")
    """
    try:
        # Build cookie jar from the pasted value
        cookies = {cookie_name: session_cookie.strip()}

        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "application/pdf,application/octet-stream,image/*,*/*"
        }

        resp = requests.get(url, cookies=cookies, headers=headers, timeout=15, allow_redirects=True)

        # Check for redirect to login page (cookie expired / invalid)
        if resp.status_code == 302 or "login" in resp.url.lower():
            return None, None, "Redirected to login — session cookie may have expired."

        if resp.status_code != 200:
            return None, None, f"Server returned status {resp.status_code}."

        content_type = resp.headers.get("Content-Type", "").lower()

        # Detect if we got an HTML page instead of a file (cookie invalid or viewer URL)
        if "text/html" in content_type:
            if "login" in resp.text.lower() or "sign in" in resp.text.lower():
                return None, None, "Session cookie invalid or expired — received login page."
            return None, None, "URL opened a web page, not a file. This link may need to be opened in a browser and downloaded manually."

        # Determine file extension from content type
        ext_map = {
            "application/pdf": ".pdf",
            "image/jpeg": ".jpg",
            "image/jpg": ".jpg",
            "image/png": ".png",
            "image/gif": ".gif",
            "application/octet-stream": ".pdf",  # assume PDF for generic binary
        }
        ext = ".pdf"  # safe default
        for mime, file_ext in ext_map.items():
            if mime in content_type:
                ext = file_ext
                break

        # Try to get filename from Content-Disposition header
        filename = None
        cd = resp.headers.get("Content-Disposition", "")
        if cd:
            fname_match = re.search(r'filename[^;=\n]*=(["\'])?(.*?)\1', cd)
            if fname_match:
                filename = fname_match.group(2).strip()

        if not filename:
            # Derive from URL
            url_path = url.split("?")[0].rstrip("/")
            filename = url_path.split("/")[-1] or f"action_plan{ext}"
            if "." not in filename:
                filename += ext

        file_bytes = BytesIO(resp.content)
        file_bytes.name = filename  # attach name so convert_file_to_images works
        file_bytes.seek(0)
        return file_bytes, filename, None

    except requests.exceptions.Timeout:
        return None, None, "Request timed out — check your network connection."
    except requests.exceptions.ConnectionError:
        return None, None, "Could not connect to the server."
    except Exception as e:
        return None, None, f"Unexpected error: {e}"


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

    # Extract "Last changed" date from the preamble (before first ---)
    last_changed = None
    lc_match = re.search(r'Last changed:\s*(\S.*)', text)
    if lc_match:
        last_changed = lc_match.group(1).strip()

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
                    "name": cond_name, "severity": severity, "description": description,
                    "css_class": css_class, "last_changed": last_changed
                })
    
    if not parsed_conditions and len(text) > 10 and "No data" not in text:
        parsed_conditions.append({
            "name": "General Medical Note", "severity": "Info", "description": text,
            "css_class": "mild", "last_changed": last_changed
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
        phones = []
        for line in lines:
            if "Relationship:" in line: relation = line.split("Relationship:")[-1].strip()
            if "Telephone:" in line:
                phone_raw = line.split("Telephone:")[-1].strip()
                if phone_raw:
                    phone_clean = re.sub(r'[^\d+]', '', phone_raw)
                    phones.append({"display": phone_raw, "link": f"tel:{phone_clean}"})
        if phones: contacts.append({"name": name, "relation": relation, "phones": phones})
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


# ─────────────────────────────────────────────────────────────────────────────
# SEQTA CONTACT PDF PARSER
# ─────────────────────────────────────────────────────────────────────────────

_SEQTA_LIG = {
    '\ufb00':'ff','\ufb01':'fi','\ufb02':'fl','\ufb03':'ffi','\ufb04':'ffl',
    '\ufb05':'st','\ufb06':'st','\ue000':'tt','\ue001':'ti','\ue003':'tt',
    '\u02a6':'tt','\uf001':'fi','\uf002':'fl',
}

def _sc(text):
    if not isinstance(text, str): return text
    for k,v in _SEQTA_LIG.items(): text = text.replace(k,v)
    out = []
    for ch in text:
        cp = ord(ch)
        if 0xE000 <= cp <= 0xF8FF:
            d = unicodedata.normalize('NFKD', ch)
            out.append(d if d != ch else '')
        else:
            out.append(ch)
    return unicodedata.normalize('NFC', ''.join(out))

_SC_STU=165; _SC_DOB=225; _SC_CON=555; _SC_YT=4
_SC_DOB_RE = re.compile(r'^\d{1,2}/\d{2}/\d{2,4}$')
_SC_GREL   = re.compile(r'^(Mother|Father|Guardian|Parent|Carer|Step|Uncle|Aunt|Grand|Relation)',re.IGNORECASE)

def _sc_col(x): 
    return 'student' if x<_SC_STU else 'dob' if x<_SC_DOB else 'contacts' if x<_SC_CON else 'medical'

def _sc_names(page):
    lines={}
    for ch in page.chars:
        if ch['x0']>=_SC_STU or not ch['text']: continue
        y=round(ch['top']/_SC_YT)*_SC_YT
        lines.setdefault(y,[]).append((ch['x0'],ch['text']))
    out={}
    for y,chars in lines.items():
        chars.sort(key=lambda c:c[0])
        t=_sc(''.join(c[1] for c in chars)).strip()
        if t: out[y]=t
    return out

def _sc_contact_lines(words):
    words=sorted(words,key=lambda w:(w['top'],w['x0']))
    lines=[]
    for w in words:
        col=_sc_col(w['x0'])
        if col not in ('dob','contacts'): continue
        t=_sc(w['text'])
        placed=False
        for line in reversed(lines):
            if abs(line['y']-w['top'])<=_SC_YT:
                line[col]=(line[col]+' '+t).strip(); placed=True; break
        if not placed:
            e={'y':w['top'],'dob':'','contacts':''}; e[col]=t; lines.append(e)
    return lines

def _sc_parse_contacts(lines):
    r={"home_address":"","home_phone":"","home_mobile":"","guardians":[]}
    af=hf=False; cur=None
    def _sv():
        if cur is not None: r["guardians"].append(cur)
    for line in lines:
        line=line.strip()
        if not line: continue
        if _SC_GREL.match(line):
            _sv()
            parts=line.split(None,1); rel=parts[0].title(); rest=parts[1].strip() if len(parts)>1 else ""
            mm=re.search(r'Mobile:\s*([\d\s\+\(\)]+)',rest,re.IGNORECASE)
            cur={"relationship":rel,"name":rest[:mm.start()].strip() if mm else rest,
                 "mobile":mm.group(1).strip() if mm else "","home":"","work":""}
            continue
        if cur is not None and re.search(r'(?:Home:|Work:|Mobile:)',line,re.IGNORECASE):
            m=re.search(r'Mobile:\s*([\d\s\+\(\)]+)',line,re.IGNORECASE)
            if m and not cur["mobile"]: cur["mobile"]=m.group(1).strip()
            m=re.search(r'(?<!\w)Home:\s*([\d\s\+\(\)]+)',line,re.IGNORECASE)
            if m: cur["home"]=m.group(1).strip()
            m=re.search(r'Work:\s*([\d\s\+\(\)]+)',line,re.IGNORECASE)
            if m: cur["work"]=m.group(1).strip()
            continue
        if not hf and re.search(r'(?<!\w)Home:',line,re.IGNORECASE):
            hm=re.search(r'(?<!\w)Home:\s*([\d\s\+\(\)]*)',line,re.IGNORECASE)
            mm=re.search(r'Mobile:\s*([\d\s\+\(\)]+)',line,re.IGNORECASE)
            if hm: r["home_phone"]=hm.group(1).strip()
            if mm: r["home_mobile"]=mm.group(1).strip()
            hf=True; continue
        if not af:
            r["home_address"]=line; af=True
    _sv(); return r

def _sc_parse_name(raw):
    r={"surname":"","first_name":"","preferred":""}
    t=raw.strip()
    if not t: return r
    pm=re.search(r'\(([^)]+)\)',t); pref=pm.group(1).strip() if pm else ""
    c=re.sub(r'\([^)]*\)','',t).strip()
    if ',' in c:
        p=c.split(',',1); sur=p[0].strip(); first=p[1].strip().split()[0] if p[1].strip() else ""
    else:
        tok=c.split(); sur=tok[0] if tok else ""; first=tok[1] if len(tok)>1 else ""
    r["surname"]=sur; r["first_name"]=first; r["preferred"]=pref if pref else first
    return r

def parse_seqta_contact_pdf_app(pdf_file):
    records=[]
    if hasattr(pdf_file,"seek"): pdf_file.seek(0)
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            words=page.extract_words(x_tolerance=3,y_tolerance=3)
            lines=_sc_contact_lines(words)
            names=_sc_names(page)
            anchors=[(l['y'],l['dob'].strip()) for l in lines if _SC_DOB_RE.match(l['dob'].strip())]
            for idx,(dob_y,dob_val) in enumerate(anchors):
                end_y=anchors[idx+1][0] if idx+1<len(anchors) else page.height
                name_raw=''; best=999
                for y,text in names.items():
                    d=abs(y-dob_y)
                    if d<=8 and d<best and text.lower() not in ('student','dob','contacts'):
                        name_raw=text; best=d
                clns=[l['contacts'] for l in lines if l['y']>=dob_y-2 and l['y']<end_y-2 and l['contacts']]
                if not name_raw: continue
                ni=_sc_parse_name(name_raw); ci=_sc_parse_contacts(clns)
                sur=ni["surname"].strip(); first=ni["first_name"].strip()
                if not sur or (len(sur)<=2 and not first): continue
                records.append({**ni,**ci,"dob":dob_val,"_raw_name":name_raw,"_raw_contacts":"\n".join(clns)})
    return records

def match_seqta_contacts_app(pdf_records, df_students):
    id_col=COLS.get('student_id','Code'); fn_col=COLS.get('first_name','First name'); sn_col=COLS.get('surname','Surname')
    exact={}; sur_map={}
    for _,row in df_students.iterrows():
        sid=str(row.get(id_col,'')).strip(); first=str(row.get(fn_col,'')).strip().lower(); sur=str(row.get(sn_col,'')).strip().lower()
        if not sid or not sur: continue
        exact[(sur,first)]=sid; sur_map.setdefault(sur,[]).append(sid)
    matched,unmatched,ambiguous={},{},[]  # use dict for ambiguous clarity
    unmatched_list=[]
    for rec in pdf_records:
        sur=rec.get('surname','').strip().lower(); first=rec.get('first_name','').strip().lower(); pref=rec.get('preferred','').strip().lower()
        sid=None
        if (sur,first) in exact: sid=exact[(sur,first)]
        elif pref and pref!=first and (sur,pref) in exact: sid=exact[(sur,pref)]
        else:
            cands=sur_map.get(sur,[])
            if len(cands)==1: sid=cands[0]
            elif len(cands)>1: ambiguous.append((rec,cands)); continue
        if sid is None:
            sur_tt=re.sub(r'ti','tt',sur); first_tt=re.sub(r'ti','tt',first); pref_tt=re.sub(r'ti','tt',pref)
            if sur_tt!=sur:
                if (sur_tt,first_tt) in exact: sid=exact[(sur_tt,first_tt)]
                elif pref_tt and pref_tt!=first_tt and (sur_tt,pref_tt) in exact: sid=exact[(sur_tt,pref_tt)]
                else:
                    cands=sur_map.get(sur_tt,[])
                    if len(cands)==1: sid=cands[0]
                    elif len(cands)>1: ambiguous.append((rec,cands)); continue
        if sid: matched[sid]=rec
        else: unmatched_list.append(rec)
    return matched, unmatched_list, ambiguous

def home_contacts_from_pdf(pdf_rec):
    if not pdf_rec: return {"contacts":[],"home_address":"","home_phone":""}
    contacts=[]
    for g in pdf_rec.get("guardians",[]):
        ph=g.get("mobile") or g.get("home") or ""
        pc=re.sub(r'[^\d+]','',ph)
        po={"display":ph,"link":f"tel:{pc}"} if pc else None
        n=g.get("name","").strip()
        if n: contacts.append({"name":n,"relation":g.get("relationship","Guardian"),"phone":po})
    hp=pdf_rec.get("home_phone","") or pdf_rec.get("home_mobile","")
    return {"contacts":contacts,"home_address":pdf_rec.get("home_address",""),"home_phone":hp}


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

def _build_parent_surname_lookup(contact_df):
    """
    Given the contact/attendance dataframe (already merged), build a dict:
        { parent_surname_lower: [ {sid, first_lower}, ... ] }
    using SC1/SC2 Preferred + Surname columns.
    Each entry stores both the student ID and the parent's first name so
    callers can require a first-name match, not just a surname match.
    Returns an empty dict if contact_df is None or columns are missing.
    """
    lookup = {}  # surname_lower -> list of {sid, first}
    if contact_df is None:
        return lookup

    c_map    = CONFIG.get('contact_file_mappings', {})
    id_col   = c_map.get('join_key', 'ID')
    sc1_sur  = c_map.get('sc1_name_sur',  'SC1 Surname')
    sc2_sur  = c_map.get('sc2_name_sur',  'SC2 Surname')
    sc1_pref = c_map.get('sc1_name_pref', 'SC1 Preferred')
    sc2_pref = c_map.get('sc2_name_pref', 'SC2 Preferred')

    for _, row in contact_df.iterrows():
        sid = str(row.get(id_col, '')).strip()
        if not sid:
            continue
        for sur_col, first_col in [(sc1_sur, sc1_pref), (sc2_sur, sc2_pref)]:
            sur   = str(row.get(sur_col,   '')).strip().lower()
            first = str(row.get(first_col, '')).strip().lower()
            if sur and sur not in ('nan', ''):
                lookup.setdefault(sur, [])
                # Avoid duplicate entries for the same sid+first
                entry = {'sid': sid, 'first': first}
                if entry not in lookup[sur]:
                    lookup[sur].append(entry)

    return lookup


def _build_parent_lookup_from_pdf(seqta_matched):
    """
    Build parent surname lookup from Seqta PDF guardian data.
    seqta_matched: { student_id: pdf_record } where each record has 'guardians'
    list of { name: "Firstname Lastname", relationship, mobile... }
    Returns: { surname_lower: [ {sid, first_lower}, ... ] }
    """
    lookup = {}
    if not seqta_matched:
        return lookup
    for sid, rec in seqta_matched.items():
        for guardian in rec.get('guardians', []):
            full_name = guardian.get('name', '').strip()
            if not full_name:
                continue
            parts = full_name.split()
            if len(parts) < 2:
                continue
            surname = parts[-1].lower()
            first   = parts[0].lower()
            entry   = {'sid': sid, 'first': first}
            lookup.setdefault(surname, [])
            if entry not in lookup[surname]:
                lookup[surname].append(entry)
    return lookup


def _read_and_dedup_csv(file_obj):
    """
    Reads a Paperly-format CSV (Email, First Name, Surname, Submission Time, Status, Value)
    and deduplicates rows by email, keeping the most recent submission.
    Returns the cleaned DataFrame.
    """
    if hasattr(file_obj, 'seek'):
        file_obj.seek(0)
    df = pd.read_csv(file_obj).fillna("")

    col_email = df.columns[0]
    col_time  = df.columns[3]

    df[col_time] = pd.to_datetime(df[col_time], errors='coerce')
    has_email = df[df[col_email].astype(str).str.strip() != ""]
    no_email  = df[df[col_email].astype(str).str.strip() == ""]
    deduped = (
        has_email
        .sort_values(col_time, ascending=False)
        .drop_duplicates(subset=[col_email], keep='first')
    )
    return pd.concat([deduped, no_email], ignore_index=True)

def match_swimming_ability(df_main, swimming_csv, contact_df=None):
    """
    Matches swimming ability to students by searching for the student's surname
    within the 'Student' column of the swimming CSV.

    CSV format (7 cols, 6 headers — Email used as implicit index by pandas):
      Email, First Name, Surname, Student, Submission Time, [Status], Swimming Ability

    Read with explicit column names to avoid the index-shift problem.

    Strategy:
    - Unique surname  → match if surname appears as a whole word in Student field
    - Duplicate surnames → require surname + first/preferred name both present
    - Deduplicates by email, keeping the most recent submission
    """
    if swimming_csv is None:
        print("\n⚠️  No swimming CSV provided - skipping")
        return {}, []

    try:
        if hasattr(swimming_csv, 'seek'):
            swimming_csv.seek(0)

        col_names = ['Email', 'First Name', 'Surname', 'Student', 'Submission Time', 'Status', 'Swimming Ability']
        swim_df = pd.read_csv(swimming_csv, names=col_names, skiprows=1).fillna("")

        student_col = 'Student'
        ability_col = 'Swimming Ability'

        print(f"\n{'='*80}")
        print("SWIMMING ABILITY MATCHING")
        print(f"{'='*80}")
        print(f"Columns: {list(swim_df.columns)}")
        print(f"Total rows: {len(swim_df)}")

        # Deduplicate by email, keep most recent
        swim_df['_time'] = pd.to_datetime(swim_df['Submission Time'], errors='coerce')
        has_email = swim_df[swim_df['Email'].str.strip() != ""]
        no_email  = swim_df[swim_df['Email'].str.strip() == ""]
        deduped = has_email.sort_values('_time', ascending=False).drop_duplicates(subset=['Email'], keep='first')
        swim_df = pd.concat([deduped, no_email], ignore_index=True)
        print(f"Rows after dedup: {len(swim_df)}")

        # Identify duplicate student surnames in the main list
        surname_counts = {}
        for _, row in df_main.iterrows():
            s = str(row[COLS['surname']]).strip().lower()
            if s:
                surname_counts[s] = surname_counts.get(s, 0) + 1
        duplicate_surnames = {s for s, c in surname_counts.items() if c > 1}
        print(f"Duplicate surnames in student list: {len(duplicate_surnames)}")

        matched = {}
        unmatched = []
        used_indices = set()
        matched_count = 0

        print(f"\n{'='*80}")
        print("MATCHING PROCESS")
        print(f"{'='*80}")

        for _, student_row in df_main.iterrows():
            student_id     = str(student_row[COLS['student_id']])
            first_name     = str(student_row[COLS['first_name']]).strip()
            preferred_name = str(student_row.get('Preferred name', '')).strip()
            surname        = str(student_row[COLS['surname']]).strip()

            if not surname:
                continue

            surname_lower = surname.lower()
            first_lower   = first_name.lower()
            pref_lower    = preferred_name.lower()
            has_dup       = surname_lower in duplicate_surnames

            match_found = False
            for swim_idx, swim_row in swim_df.iterrows():
                if swim_idx in used_indices:
                    continue

                student_name_field = str(swim_row.get(student_col, '')).strip().lower()
                ability = str(swim_row.get(ability_col, '')).strip()

                if not ability or ability.lower() in ('nan', 'submitted', ''):
                    continue

                surname_pattern = r'\b' + re.escape(surname_lower) + r'\b'

                if not has_dup:
                    if re.search(surname_pattern, student_name_field):
                        matched[student_id] = ability
                        used_indices.add(swim_idx)
                        match_found = True
                        matched_count += 1
                        if matched_count <= 5:
                            print(f"[{matched_count}] ✓ {surname}, {first_name} → '{swim_row[student_col]}' : {ability}")
                        break
                else:
                    surname_match = re.search(surname_pattern, student_name_field)
                    first_match   = re.search(r'\b' + re.escape(first_lower) + r'\b', student_name_field) if first_lower else None
                    pref_match    = re.search(r'\b' + re.escape(pref_lower)  + r'\b', student_name_field) if pref_lower  else None
                    if surname_match and (first_match or pref_match):
                        matched[student_id] = ability
                        used_indices.add(swim_idx)
                        match_found = True
                        matched_count += 1
                        if matched_count <= 5:
                            print(f"[{matched_count}] ✓ {surname}, {first_name} → '{swim_row[student_col]}' : {ability}")
                        break

            if not match_found and matched_count <= 10:
                print(f"[ ] ✗ {surname}, {first_name} (ID: {student_id}) — not found in swimming CSV")

        # Collect unmatched swimming rows for manual assignment
        for swim_idx, swim_row in swim_df.iterrows():
            if swim_idx not in used_indices:
                student_name = str(swim_row.get(student_col, '')).strip()
                ability = str(swim_row.get(ability_col, '')).strip()
                if student_name and ability and ability.lower() not in ('nan', 'submitted', ''):
                    unmatched.append({'student_name': student_name, 'ability': ability, 'index': swim_idx})

        print(f"\n✓ Matched: {len(matched)}  ✗ Unmatched rows: {len(unmatched)}")
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
    Matches dietary requirements to students by searching for the student's surname
    within the 'Student' column of the dietary CSV.

    CSV format (7 cols, 6 headers — Email used as implicit index by pandas):
      Email, First Name, Surname, Student, Submission Time, [Status], Dietary Requirements

    Read with explicit column names to avoid the index-shift problem.

    Strategy:
    - Unique surname  → match if surname appears as a whole word in Student field
    - Duplicate surnames → require surname + first/preferred name both present
    - Deduplicates by email, keeping the most recent submission
    """
    try:
        if hasattr(dietary_csv, 'seek'):
            dietary_csv.seek(0)

        col_names = ['Email', 'First Name', 'Surname', 'Student', 'Submission Time', 'Status', 'Dietary Requirements']
        dietary_df = pd.read_csv(dietary_csv, names=col_names, skiprows=1).fillna("")

        student_col = 'Student'
        dietary_col = 'Dietary Requirements'

        print(f"\n{'='*80}")
        print("DIETARY REQUIREMENTS MATCHING")
        print(f"{'='*80}")
        print(f"Columns: {list(dietary_df.columns)}")
        print(f"Total rows: {len(dietary_df)}")

        # Deduplicate by email, keep most recent
        dietary_df['_time'] = pd.to_datetime(dietary_df['Submission Time'], errors='coerce')
        has_email = dietary_df[dietary_df['Email'].str.strip() != ""]
        no_email  = dietary_df[dietary_df['Email'].str.strip() == ""]
        deduped = has_email.sort_values('_time', ascending=False).drop_duplicates(subset=['Email'], keep='first')
        dietary_df = pd.concat([deduped, no_email], ignore_index=True)
        print(f"Rows after dedup: {len(dietary_df)}")

        # Identify duplicate student surnames
        surname_counts = {}
        for _, row in df_main.iterrows():
            s = str(row[COLS['surname']]).strip().lower()
            if s:
                surname_counts[s] = surname_counts.get(s, 0) + 1
        duplicate_surnames = {s for s, c in surname_counts.items() if c > 1}
        print(f"Duplicate surnames in student list: {len(duplicate_surnames)}")

        matched = {}
        unmatched = []
        used_indices = set()
        matched_count = 0

        print(f"\n{'='*80}")
        print("MATCHING PROCESS")
        print(f"{'='*80}")

        for _, student_row in df_main.iterrows():
            student_id     = str(student_row[COLS['student_id']])
            first_name     = str(student_row[COLS['first_name']]).strip()
            preferred_name = str(student_row.get('Preferred name', '')).strip()
            surname        = str(student_row[COLS['surname']]).strip()

            if not surname:
                continue

            surname_lower = surname.lower()
            first_lower   = first_name.lower()
            pref_lower    = preferred_name.lower()
            has_dup       = surname_lower in duplicate_surnames

            match_found = False
            for diet_idx, diet_row in dietary_df.iterrows():
                if diet_idx in used_indices:
                    continue

                student_name_field = str(diet_row.get(student_col, '')).strip().lower()
                dietary_req = str(diet_row.get(dietary_col, '')).strip()

                # Normalise empty / nil / N/A
                if not dietary_req or dietary_req.lower() in ('nan', 'submitted', '', 'nil', 'n/a'):
                    dietary_req = "No concerns listed"

                surname_pattern = r'\b' + re.escape(surname_lower) + r'\b'

                if not has_dup:
                    if re.search(surname_pattern, student_name_field):
                        matched[student_id] = dietary_req
                        used_indices.add(diet_idx)
                        match_found = True
                        matched_count += 1
                        if matched_count <= 5:
                            print(f"[{matched_count}] ✓ {surname}, {first_name} → '{diet_row[student_col]}' : {dietary_req[:50]}...")
                        break
                else:
                    surname_match = re.search(surname_pattern, student_name_field)
                    first_match   = re.search(r'\b' + re.escape(first_lower) + r'\b', student_name_field) if first_lower else None
                    pref_match    = re.search(r'\b' + re.escape(pref_lower)  + r'\b', student_name_field) if pref_lower  else None
                    if surname_match and (first_match or pref_match):
                        matched[student_id] = dietary_req
                        used_indices.add(diet_idx)
                        match_found = True
                        matched_count += 1
                        if matched_count <= 5:
                            print(f"[{matched_count}] ✓ {surname}, {first_name} → '{diet_row[student_col]}' : {dietary_req[:50]}...")
                        break

            if not match_found and matched_count <= 10:
                print(f"[ ] ✗ {surname}, {first_name} (ID: {student_id}) — not found in dietary CSV")

        # Collect unmatched dietary rows for manual assignment
        for diet_idx, diet_row in dietary_df.iterrows():
            if diet_idx not in used_indices:
                student_name = str(diet_row.get(student_col, '')).strip()
                dietary_req  = str(diet_row.get(dietary_col, '')).strip()
                if not dietary_req or dietary_req.lower() in ('nan', 'submitted', '', 'nil', 'n/a'):
                    dietary_req = "No concerns listed"
                if student_name:
                    unmatched.append({'student_name': student_name, 'dietary_req': dietary_req, 'index': diet_idx})

        print(f"\n✓ Matched: {len(matched)}  ✗ Unmatched rows: {len(unmatched)}")
        print(f"{'='*80}\n")
        return matched, unmatched

    except Exception as e:
        st.error(f"Error processing dietary CSV: {e}")
        import traceback
        print(traceback.format_exc())
        return {}, []

def match_photo_permissions(df_main, photo_perm_csv):
    """
    Matches photo permission responses to students using a three-tier strategy:

    Tier 1 — Emergency contacts from the student list CSV.
             Matches the parent's first name AND surname (both required as
             whole words) against names parsed from each student's Emergency
             Notes field. Works with no optional files uploaded.
    Tier 2 — Contact CSV SC1/SC2 Surname lookup (if Attendance CSV uploaded).

    No surname-only fallback is used — parent name must explicitly appear
    in a student's emergency contacts or contact CSV to count as a match.
    Students with no match are marked 'No Response'.

    A student is 'Yes' only if BOTH questions are answered 'Yes'.
    Any 'No' answer → 'No'. No match found → 'No Response'.

    CSV format: Email, First Name, Surname, Submission Time, Status, Q1, Q2
    """
    try:
        df = _read_and_dedup_csv(photo_perm_csv)

        col_first   = df.columns[1]
        col_surname = df.columns[2]
        q_cols      = [df.columns[-2], df.columns[-1]]

        print(f"\n{'='*80}")
        print("PHOTO PERMISSIONS MATCHING")
        print(f"{'='*80}")
        print(f"Columns: {list(df.columns)}")
        print(f"Rows (after dedup): {len(df)}")
        print(f"  Q1: '{q_cols[0]}'")
        print(f"  Q2: '{q_cols[1]}'")

        # ── Build permission records list: [{first, surname, result}] ─────
        # Store each parent as separate fields so we can match first AND last
        # independently against emergency contact names.
        perm_records = []
        for _, row in df.iterrows():
            p_first   = str(row[col_first]).strip().lower()
            p_surname = str(row[col_surname]).strip().lower()
            q1 = str(row[q_cols[0]]).strip().lower()
            q2 = str(row[q_cols[1]]).strip().lower()
            result = 'Yes' if (q1 == 'yes' and q2 == 'yes') else 'No'
            if p_first and p_surname:
                perm_records.append({'first': p_first, 'surname': p_surname, 'result': result})

        def _name_matches_perm(emerg_name_lower, perm):
            """
            Returns True if the permission record's first name AND surname
            both appear as whole words within the emergency contact name string.
            Handles middle names and any word order.
            e.g. emerg_name = "jessica anne gray"
                 perm first="jessica" surname="gray" → True
                 perm first="jessica" surname="smith" → False
            """
            first_pat   = r'\b' + re.escape(perm['first'])   + r'\b'
            surname_pat = r'\b' + re.escape(perm['surname']) + r'\b'
            return (re.search(first_pat, emerg_name_lower) is not None and
                    re.search(surname_pat, emerg_name_lower) is not None)

        # ── Tier 2 prep: guardian lookup from Seqta PDF (incl. manual matches) ─
        seqta_matched = st.session_state.get('seqta_contact_matched', {}).copy()
        # Include manually matched students so their guardians are also checked
        seqta_manual    = st.session_state.get('seqta_contact_manual', {})
        seqta_unmatched = st.session_state.get('seqta_contact_unmatched', [])
        for idx, msid in seqta_manual.items():
            for rec in seqta_unmatched:
                if rec.get('_index') == idx:
                    seqta_matched[msid] = rec
                    break
        if seqta_matched:
            parent_lookup = _build_parent_lookup_from_pdf(seqta_matched)
            source_label  = "Seqta PDF guardians"
        else:
            # Fallback to old attendance CSV for backward compatibility
            contact_df    = st.session_state.get('contact_csv_df', None)
            parent_lookup = _build_parent_surname_lookup(contact_df)
            source_label  = "Attendance CSV (SC1/SC2)"
        using_contact = bool(parent_lookup)
        print(f"Emergency contacts: always active (first + last name required)")
        print(f"Parent lookup ({source_label}): {using_contact} ({len(parent_lookup)} surnames indexed)")

        # ── Tier 3 prep: student own-surname lookup ───────────────────────────
        student_surname_lookup = {}
        for _, row in df_main.iterrows():
            sid   = str(row[COLS['student_id']])
            sname = str(row[COLS['surname']]).strip().lower()
            if sname:
                student_surname_lookup.setdefault(sname, set()).add(sid)

        # ── Start every student as No Response ───────────────────────────────
        permissions = {str(row[COLS['student_id']]): 'No Response' for _, row in df_main.iterrows()}

        print(f"\n{'='*80}")
        print("MATCHING PROCESS")
        print(f"{'='*80}")

        for _, student_row in df_main.iterrows():
            sid = str(student_row[COLS['student_id']])

            # Collect ALL confirmed matches for this student across all tiers.
            # A confirmed match means the parent name was explicitly found in
            # this student's emergency contacts or contact CSV — not just a
            # surname coincidence with an unrelated person.
            # "No wins" only among confirmed matches for the same student.
            confirmed_matches = []  # list of (result, tier_description)

            # ── Tier 1: match parent first + last name against emergency contacts
            emerg_text  = str(student_row.get(COLS['emergency_notes'], '')).strip()
            emerg_names = parse_emergency_contact_names(emerg_text)

            # Build the student's own name variants to exclude self-matches.
            # A student's own name should never be treated as an emergency contact.
            s_first     = str(student_row[COLS['first_name']]).strip().lower()
            s_pref      = str(student_row.get('Preferred name', '')).strip().lower()
            s_surname   = str(student_row[COLS['surname']]).strip().lower()

            for emerg_name in emerg_names:
                # Skip if this emergency contact name is the student themselves
                emerg_parts = emerg_name.split()
                if len(emerg_parts) >= 2:
                    emerg_first   = emerg_parts[0]
                    emerg_surname = emerg_parts[-1]
                    is_student = (
                        emerg_surname == s_surname and
                        (emerg_first == s_first or (s_pref and emerg_first == s_pref))
                    )
                    if is_student:
                        print(f"  [skip] emergency contact '{emerg_name}' matches student's own name — ignored")
                        continue

                for perm in perm_records:
                    if _name_matches_perm(emerg_name, perm):
                        tier_desc = (f"emergency contact '{emerg_name}' "
                                     f"matched '{perm['first']} {perm['surname']}'")
                        confirmed_matches.append((perm['result'], tier_desc))
                        # Keep going — don't break. A student may have two parents
                        # both listed as emergency contacts who both filled the form.

            # ── Tier 2: Contact CSV SC1/SC2 — match perm first+last against
            #            the SC1/SC2 preferred+surname linked to this student
            if not confirmed_matches and using_contact:
                for perm in perm_records:
                    entries = parent_lookup.get(perm['surname'], [])
                    for entry in entries:
                        if entry['sid'] != sid:
                            continue
                        # Surname matches and is linked to this student.
                        # Also require first name to match (or be blank in contact CSV).
                        contact_first = entry['first']
                        first_pat = r'\b' + re.escape(perm['first']) + r'\b'
                        first_ok = (
                            not contact_first or
                            contact_first in ('nan', '') or
                            re.search(first_pat, contact_first) is not None
                        )
                        if first_ok:
                            tier_desc = f"contact CSV '{perm['first']} {perm['surname']}'"
                            confirmed_matches.append((perm['result'], tier_desc))
                            break

            # ── Resolve: among confirmed matches, No wins only over Yes.
            # An unrelated person sharing a surname is never in confirmed_matches
            # so their No cannot affect this student.
            if confirmed_matches:
                # If any confirmed parent said No, result is No
                if any(r == 'No' for r, _ in confirmed_matches):
                    final_result = 'No'
                else:
                    final_result = 'Yes'
                tiers = ', '.join(t for _, t in confirmed_matches)
                permissions[sid] = final_result
                print(f"  {final_result:3s} ← student {sid} via {tiers}")
            else:
                print(f"  --- ← student {sid} — no confirmed match (No Response)")

        yes_count = sum(1 for v in permissions.values() if v == 'Yes')
        no_count  = sum(1 for v in permissions.values() if v == 'No')
        nr_count  = sum(1 for v in permissions.values() if v == 'No Response')
        print(f"\nResults: Yes={yes_count}  No={no_count}  No Response={nr_count}")
        print(f"{'='*80}\n")
        return permissions

    except Exception as e:
        import traceback
        print(f"Error processing photo permissions CSV: {e}")
        print(traceback.format_exc())
        return {}

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

                    # SAME-LINE GUARD — with wrapped-surname relaxation.
                    # Multi-word surnames (e.g. "Jarretto Handerstaay") and
                    # hyphenated names with a space ("Duskett- McDann") can
                    # wrap onto the next line in a narrow photo-label column.
                    # In those cases the words' `top` values differ by one
                    # full line height (~12 px), exceeding SAME_LINE_TOL=8
                    # and causing a missed match.
                    # For multi-word phrases we allow the relaxed tolerance
                    # when the words stay inside the same narrow column
                    # (x-centre spread < 70 px) and appear in reading order.
                    tops = [w['top'] for w in phrase_objs]
                    vertical_spread = max(tops) - min(tops)
                    if vertical_spread > SAME_LINE_TOL:
                        if length > 1:
                            # Are all words horizontally within the same narrow column?
                            x_centres = [(w['x0'] + w['x1']) / 2 for w in phrase_objs]
                            same_col   = (max(x_centres) - min(x_centres)) < 70
                            # Also allow when the first word ends in '-' (hyphenated wrap)
                            is_hyphen_wrap = phrase_objs[0]['text'].rstrip().endswith('-')
                            # Words must appear in descending / non-reversed order (top-to-bottom)
                            in_order = all(
                                phrase_objs[j]['top'] <= phrase_objs[j+1]['top'] + 5
                                for j in range(len(phrase_objs) - 1)
                            )
                            if (same_col or is_hyphen_wrap) and in_order and vertical_spread <= 22:
                                pass  # allow this wrapped multi-word phrase
                            else:
                                continue
                        else:
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

  /* ── Feature selection cards — full-card clickable buttons ── */
  /* Target via :has() on the column that contains the unique marker span */
  [data-testid="stColumn"]:has(#fc-booklet-marker) [data-testid="stBaseButton-secondary"] > button,
  [data-testid="stColumn"]:has(#fc-group-marker) [data-testid="stBaseButton-secondary"] > button {
    all: unset !important;
    display: block !important;
    width: 100% !important;
    background: #ffffff !important;
    border: 2px solid #e2e5ee !important;
    border-radius: 14px !important;
    padding: 32px 28px !important;
    text-align: center !important;
    cursor: pointer !important;
    transition: border-color 0.18s, box-shadow 0.18s, transform 0.14s !important;
    color: #6b6f82 !important;
    font-size: 0.84rem !important;
    line-height: 1.65 !important;
    box-sizing: border-box !important;
    min-height: 220px !important;
    white-space: pre-line !important;
    letter-spacing: 0 !important;
  }
  [data-testid="stColumn"]:has(#fc-booklet-marker) [data-testid="stBaseButton-secondary"] > button p,
  [data-testid="stColumn"]:has(#fc-group-marker) [data-testid="stBaseButton-secondary"] > button p {
    margin: 0 !important;
    padding: 0 !important;
  }
  [data-testid="stColumn"]:has(#fc-booklet-marker) [data-testid="stBaseButton-secondary"] > button:hover,
  [data-testid="stColumn"]:has(#fc-group-marker) [data-testid="stBaseButton-secondary"] > button:hover {
    border-color: #1a7f6e !important;
    box-shadow: 0 6px 24px rgba(26,127,110,0.13) !important;
    transform: translateY(-3px) !important;
    color: #1a1d2e !important;
  }
</style>""", unsafe_allow_html=True)


st.markdown("""<style>
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



  /* ── Group creator output box ── */
  .group-output-wrap {
    background: #f0faf8;
    border: 2px solid #a8ddd6;
    border-radius: 10px;
    padding: 16px 18px;
    margin-top: 12px;
  }
  .group-output-label {
    font-size: 0.75rem; font-weight: 700; color: #1a7f6e;
    text-transform: uppercase; letter-spacing: 0.07em; margin-bottom: 8px;
  }
  .seqta-instruction {
    background: #fff8e6;
    border-left: 4px solid #e8960a;
    border-radius: 6px;
    padding: 10px 14px;
    font-size: 0.82rem;
    color: #7a5a00;
    margin-top: 10px;
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
    st.markdown("**📋 Medical Booklet Tools**")
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
if "auto_downloaded_plans" not in st.session_state: st.session_state.auto_downloaded_plans = {}
if "auto_downloaded_plan_files" not in st.session_state: st.session_state.auto_downloaded_plan_files = {}
if "manual_plan_uploads" not in st.session_state: st.session_state.manual_plan_uploads = {}

# ── Build only the tabs that are needed for the current feature ──────────────
_active_feature = st.session_state.get("active_feature", None)

if _active_feature == "booklet":
    _tab_labels = ["  🏠 Home  ", "  📋 Booklet Setup  ", "  ⚙️ Process & Generate  "]
    _tabs = st.tabs(_tab_labels)
    t0, t1, t2 = _tabs
    t3 = None
elif _active_feature == "group":
    _tab_labels = ["  🏠 Home  ", "  👥 Group Creator  "]
    _tabs = st.tabs(_tab_labels)
    t0, t3 = _tabs
    t1 = t2 = None
else:
    _tab_labels = ["  🏠 Home  "]
    _tabs = st.tabs(_tab_labels)
    t0 = _tabs[0]
    t1 = t2 = t3 = None

# ── Auto-tab-switch helper (injected as a hidden iframe via st.components) ────
def _inject_tab_click(tab_index):
    """Reliably clicks a Streamlit tab by index after the DOM has settled.
    Uses a time-based nonce so Streamlit always treats this as new content
    and re-renders the iframe — otherwise identical HTML is skipped on rerun."""
    import time
    nonce = int(time.time() * 1000)
    fn = f"clickTab_{tab_index}_{nonce}"
    st.components.v1.html(f"""
    <script>
        var _attempts_{nonce} = 0;
        function {fn}() {{
            var tabs = window.parent.document.querySelectorAll('[data-testid="stTabs"] [role="tab"]');
            if (tabs.length > {tab_index} && tabs[{tab_index}]) {{
                tabs[{tab_index}].click();
            }} else if (_attempts_{nonce} < 20) {{
                _attempts_{nonce}++;
                setTimeout({fn}, 100);
            }}
        }}
        setTimeout({fn}, 200);
    </script>
    """, height=0)

# Auto-switch: → Booklet Setup tab (index 1 when feature=booklet)
if st.session_state.get("_go_setup"):
    st.session_state._go_setup = False
    _inject_tab_click(1)

# Auto-switch: → Group Creator tab (index 1 when feature=group)
if st.session_state.get("_go_group"):
    st.session_state._go_group = False
    _inject_tab_click(1)

# Auto-switch: → Process & Generate tab (index 2 when feature=booklet)
if st.session_state.get("_active_tab") == 1:
    st.session_state._active_tab = None
    _inject_tab_click(2)

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 0 — HOME / FEATURE SELECTOR
# ═══════════════════════════════════════════════════════════════════════════════
with t0:
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("### What would you like to do?")
    st.markdown("Choose a tool below to get started.")
    st.markdown("<br>", unsafe_allow_html=True)

    home_col1, home_col2 = st.columns(2)

    with home_col1:
        # Hidden marker lets CSS target and style this column's button as a card
        st.markdown('<span id="fc-booklet-marker" style="display:none"></span>', unsafe_allow_html=True)
        if st.button(
            "📋\n\n**Medical Booklet Creator**\n\nGenerate student medical profile PDFs for excursions — medical info, emergency contacts, swimming ability, dietary requirements and more.",
            use_container_width=True,
            key="home_booklet_btn"
        ):
            st.session_state.active_feature = 'booklet'
            st.session_state._go_setup = True
            st.rerun()

    with home_col2:
        # Hidden marker lets CSS target and style this column's button as a card
        st.markdown('<span id="fc-group-marker" style="display:none"></span>', unsafe_allow_html=True)
        if st.button(
            "👥\n\n**SEQTA Group Creator**\n\nPaste student email addresses and the app looks up their student codes — ready to paste into SEQTA to create a custom group.",
            use_container_width=True,
            key="home_group_btn"
        ):
            st.session_state.active_feature = 'group'
            st.session_state._go_group = True
            st.rerun()

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1 — SETUP
# ═══════════════════════════════════════════════════════════════════════════════
if t1 is not None:
 with t1:

    st.session_state.project_title = st.text_input(
        "Booklet title",
        st.session_state.project_title,
        placeholder="e.g. Year 9 Camp — March 2025"
    )

    # ── Required documents ────────────────────────────────────────────────────
    st.markdown('<div class="section-head">Required — from Seqta</div>', unsafe_allow_html=True)

    col_a, col_b, col_b2 = st.columns(3)
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

    with col_b2:
        st.markdown(f"""
        <div class="upload-card">
          <div class="upload-card-label">Excursion Student Info PDF</div>
          <div class="upload-card-desc">The "Excursion contact &amp; medical info" report from Seqta — provides home address, phone numbers and parent/guardian contacts.</div>
          <a class="seqta-link" href="{SEQTA_URL}" target="_blank">↗ Open in Seqta</a>
        </div>
        """, unsafe_allow_html=True)
        seqta_contact_pdf = st.file_uploader("Excursion Student Info PDF", type="pdf", label_visibility="collapsed", key="seqta_contact_pdf_uploader")

    # ── Optional documents ────────────────────────────────────────────────────
    st.markdown('<div class="section-head">Optional — from Paperly forms</div>', unsafe_allow_html=True)

    contact_csv = None  # replaced by Excursion Student Info PDF

    col_c, col_d, col_e = st.columns(3)
    with col_c:
        st.markdown("""
        <div class="upload-card optional">
          <div class="upload-card-label">Swimming Ability CSV</div>
          <div class="upload-card-desc">Adds swimming competency to each student profile.</div>
        </div>
        """, unsafe_allow_html=True)
        swimming_csv = st.file_uploader("Swimming Ability CSV", type="csv", label_visibility="collapsed")

    with col_d:
        st.markdown("""
        <div class="upload-card optional">
          <div class="upload-card-label">Dietary Requirements CSV</div>
          <div class="upload-card-desc">Adds dietary needs and generates a summary table.</div>
        </div>
        """, unsafe_allow_html=True)
        dietary_csv = st.file_uploader("Dietary Requirements CSV", type="csv", label_visibility="collapsed")

    with col_e:
        st.markdown("""
        <div class="upload-card optional">
          <div class="upload-card-label">Photo Permissions CSV</div>
          <div class="upload-card-desc">Adds photo permission status to each profile and generates a no-permission list.</div>
        </div>
        """, unsafe_allow_html=True)
        photo_perm_csv = st.file_uploader("Photo Permissions CSV", type="csv", label_visibility="collapsed")

    # ── File processing ────────────────────────────────────────────────────────
    if csv:
        df_temp = pd.read_csv(csv).fillna("")
        st.session_state.df = df_temp
        st.session_state.df_final = df_temp
        st.success("✅ Student list loaded")

    # ── Seqta Contact PDF ──────────────────────────────────────────────────────
    if seqta_contact_pdf and "df_final" in st.session_state:
        try:
            with st.spinner("Parsing Excursion Student Info PDF…"):
                _pdf_recs = parse_seqta_contact_pdf_app(seqta_contact_pdf)
            _sc_matched, _sc_unmatched, _sc_ambiguous = match_seqta_contacts_app(
                _pdf_recs, st.session_state.df_final
            )
            st.session_state.seqta_contact_matched   = _sc_matched
            # Store unmatched + ambiguous together with an index for manual matching
            _all_unmatched = _sc_unmatched + [r for r, _ in _sc_ambiguous]
            st.session_state.seqta_contact_unmatched = [
                dict(rec, _index=i) for i, rec in enumerate(_all_unmatched)
            ]
            st.session_state.seqta_contact_manual = {}
            n_m = len(_sc_matched); n_u = len(_all_unmatched)
            if n_u == 0:
                st.success(f"✅ Excursion PDF: all {n_m} students matched")
            else:
                st.warning(f"⚠️ Excursion PDF: {n_m} matched · {n_u} need manual matching in Process tab")
        except Exception as e:
            st.error(f"Error parsing Excursion PDF: {e}")
    elif seqta_contact_pdf and "df_final" not in st.session_state:
        st.warning("Upload the Student List CSV at the same time as the Excursion PDF.")

    if swimming_csv:
        st.session_state.swimming_csv = swimming_csv
        st.success("✅ Swimming ability CSV loaded")

    if dietary_csv:
        st.session_state.dietary_csv = dietary_csv
        st.success("✅ Dietary requirements CSV loaded")

    if photo_perm_csv:
        st.session_state.photo_perm_csv = photo_perm_csv
        st.success("✅ Photo permissions CSV loaded")

    if photos:
        path = os.path.join(TEMP_DIR, "photos.pdf")
        with open(path, "wb") as f: f.write(photos.getbuffer())
        st.session_state.photo_pdf = path
        st.success("✅ Photos loaded")

    # ── Navigate to Process & Generate ───────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    st.divider()
    ready = "df_final" in st.session_state and "photo_pdf" in st.session_state and "seqta_contact_matched" in st.session_state
    if ready:
        if st.button("\u25b6\u2002 Process & Generate \u2192", type="primary", use_container_width=True):
            st.session_state._active_tab = 1
            st.rerun()
    else:
        st.button("\u25b6\u2002 Process & Generate \u2192", type="primary", use_container_width=True, disabled=True)
        st.caption("Upload all three required files above to continue.")

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2 — PROCESS & GENERATE
# ═══════════════════════════════════════════════════════════════════════════════
if t2 is not None:
 with t2:

    if "df_final" not in st.session_state or "photo_pdf" not in st.session_state:
        st.info("Upload a Student List CSV and Photos PDF in the Setup tab first.")


    if "df_final" in st.session_state and "photo_pdf" in st.session_state:
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

                if 'photo_perm_csv' in st.session_state:
                    perm_map = match_photo_permissions(df_final, st.session_state.photo_perm_csv)
                    st.session_state.photo_permissions_map = perm_map

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

            # ── Seqta contact manual matching ──────────────────────────────────
            _sc_unmatched = st.session_state.get('seqta_contact_unmatched', [])
            _sc_matched   = st.session_state.get('seqta_contact_matched', {})
            if _sc_unmatched:
                with st.expander(f"⚠️  {len(_sc_unmatched)} contact record(s) need manual matching  ({len(_sc_matched)} matched automatically)", expanded=True):
                    st.caption("These students were found in the Excursion PDF but could not be automatically matched. Assign each to the correct student.")
                    for _item in _sc_unmatched:
                        _idx = _item.get('_index', id(_item))
                        _c1, _c2 = st.columns([2, 3])
                        with _c1:
                            st.markdown(f"**PDF name:** {_item.get('surname','')} {_item.get('first_name','')}")
                            if _item.get('home_address'):
                                st.caption(f"📍 {_item['home_address']}")
                            for _g in _item.get('guardians', []):
                                _phones = ' · '.join(filter(None, [_g.get('mobile'), _g.get('home'), _g.get('work')]))
                                st.caption(f"{_g.get('relationship','')}: {_g.get('name','')}  {_phones}")
                        with _c2:
                            _sel = st.selectbox("Assign to student:", options=student_options, key=f"sc_sel_{_idx}")
                            if _sel != "(Skip)":
                                st.session_state.seqta_contact_manual[_idx] = name_to_id_map[_sel]
                            elif _idx in st.session_state.seqta_contact_manual:
                                del st.session_state.seqta_contact_manual[_idx]
                        st.divider()
            elif _sc_matched:
                st.success(f"✅ All {len(_sc_matched)} contact records matched automatically")

            # Photo permissions summary
            if 'photo_perm_csv' in st.session_state:
                perm_map = st.session_state.get('photo_permissions_map', {})
                no_count = sum(1 for v in perm_map.values() if v == 'No')
                nr_count = sum(1 for v in perm_map.values() if v == 'No Response')
                yes_count = sum(1 for v in perm_map.values() if v == 'Yes')
                if no_count + nr_count > 0:
                    st.warning(f"📷 Photo Permissions: {yes_count} Yes · {no_count} No · {nr_count} No Response")
                else:
                    st.success(f"✅ Photo Permissions: All {yes_count} students have given permission")

            # ── Step 3: Medical plans ─────────────────────────────────────────────
            st.markdown('<div class="section-head">Step 3 — Medical action plans</div>', unsafe_allow_html=True)

            detected = st.session_state.get('detected_plans', {})

            # ── Advanced Options (session cookie + auto-download) ─────────────────
            if detected:
                with st.expander("⚙️ Advanced Options — Auto-download plans"):
                    st.markdown("**Auto-download all plans using your portal session**")
                    st.caption(
                        "This uses your existing browser login to download action plans automatically. "
                        "Your credentials are never stored — only the temporary session value is used."
                    )

                    # Cookie name hint (Synweb/Seqta typically uses one of these)
                    PORTAL_HOST = CONFIG['app_settings'].get('school_portal_url', '')
                    portal_domain = PORTAL_HOST.replace("https://", "").replace("http://", "").split("/")[0]

                    st.markdown("**How to get your session cookie:**")
                    st.markdown(f"""
    1. Log into [{portal_domain}]({PORTAL_HOST}) in Chrome or Safari as normal
    2. Press **F12** to open DevTools (or right-click anywhere → **Inspect**)
    3. Click the **Application** tab (Chrome) or **Storage** tab (Safari)
    4. In the left panel: **Cookies** → click `{portal_domain}`
    5. Find the cookie named **`ASP.NET_SessionId`** (or `SEQTASESSION`)
    6. Click it and copy the **Value** column
    7. Paste it below
    """)
                    st.info("💡 The cookie expires when you log out of the portal. If auto-download fails, log back in and copy a fresh value.", icon="ℹ️")

                    col_cookie, col_name = st.columns([3, 1])
                    with col_cookie:
                        cookie_val = st.text_input(
                            "Session cookie value",
                            value=st.session_state.get("_portal_cookie", ""),
                            type="password",
                            placeholder="Paste cookie value here…",
                            key="portal_cookie_input"
                        )
                    with col_name:
                        cookie_name = st.text_input(
                            "Cookie name",
                            value=st.session_state.get("_portal_cookie_name", "ASP.NET_SessionId"),
                            placeholder="ASP.NET_SessionId",
                            key="portal_cookie_name_input"
                        )

                    if cookie_val:
                        st.session_state["_portal_cookie"] = cookie_val
                    if cookie_name:
                        st.session_state["_portal_cookie_name"] = cookie_name

                    n_plans_total = sum(len(plans) for plans in detected.values())
                    btn_label = f"⬇ Auto-download all {n_plans_total} plan{'s' if n_plans_total != 1 else ''}"

                    if not cookie_val:
                        st.button(btn_label, disabled=True, help="Paste your session cookie above first")
                    else:
                        if st.button(btn_label, type="primary"):
                            if "auto_downloaded_plans" not in st.session_state:
                                st.session_state.auto_downloaded_plans = {}

                            download_results = []
                            prog_bar = st.progress(0)
                            total_plans = n_plans_total
                            done = 0

                            for sid, plans in detected.items():
                                s_name = id_to_name_map.get(sid, sid)
                                for p_idx, plan in enumerate(plans):
                                    url = plan.get('url')
                                    if not url:
                                        download_results.append((s_name, plan['condition'], False, "No URL available"))
                                        done += 1
                                        prog_bar.progress(done / total_plans)
                                        continue

                                    file_obj, filename, error = auto_download_plan(
                                        url,
                                        cookie_val,
                                        cookie_name=cookie_name or "ASP.NET_SessionId"
                                    )

                                    if file_obj:
                                        # Store raw bytes + filename as a plain tuple so they
                                        # survive st.rerun() serialisation. BytesIO objects are
                                        # not reliably preserved across reruns in session_state.
                                        plan_key = f"{sid}_{p_idx}"
                                        if "auto_downloaded_plan_files" not in st.session_state:
                                            st.session_state.auto_downloaded_plan_files = {}
                                        file_obj.seek(0)
                                        st.session_state.auto_downloaded_plan_files[plan_key] = (file_obj.read(), filename)
                                        st.session_state.auto_downloaded_plans[plan_key] = {
                                            "filename": filename, "sid": sid, "condition": plan['condition']
                                        }
                                        download_results.append((s_name, plan['condition'], True, filename))
                                    else:
                                        download_results.append((s_name, plan['condition'], False, error))

                                    done += 1
                                    prog_bar.progress(done / total_plans)

                            prog_bar.empty()

                            # Show results summary
                            successes = [r for r in download_results if r[2]]
                            failures  = [r for r in download_results if not r[2]]

                            if successes:
                                st.success(f"✅ Downloaded {len(successes)} of {total_plans} plans successfully")
                            if failures:
                                st.warning(f"⚠️ {len(failures)} plan{'s' if len(failures) != 1 else ''} could not be downloaded:")
                                for s_name, condition, _, reason in failures:
                                    st.caption(f"• **{s_name}** — {condition}: {reason}")

                            if successes:
                                st.rerun()

            # ── Per-student plan list ─────────────────────────────────────────────
            if "manual_plan_uploads" not in st.session_state:
                st.session_state.manual_plan_uploads = {}

            if detected:
                for sid, plans in detected.items():
                    s_name = id_to_name_map.get(sid, sid)
                    with st.container():
                        st.markdown(f"**{s_name}**")
                        for p_idx, plan in enumerate(plans):
                            col1, col2 = st.columns([3, 2])
                            with col1:
                                st.markdown(f"**{plan['condition']}**")
                                if plan.get('url'):
                                    st.markdown(f"[↗ Open document]({plan['url']})")
                                plan_key = f"{sid}_{p_idx}"
                                ad = st.session_state.get("auto_downloaded_plans", {}).get(plan_key)
                                if ad:
                                    st.caption(f"✅ Auto-downloaded: {ad['filename']}")
                                elif st.session_state.manual_plan_uploads.get(plan_key):
                                    fname = st.session_state.manual_plan_uploads[plan_key][1]
                                    st.caption(f"✅ Uploaded: {fname}")
                            with col2:
                                upload_label = f"Upload {plan['condition']}"
                                existing_key = f"plan_upload_{sid}_{p_idx}"
                                plan_key = f"{sid}_{p_idx}"
                                if st.session_state.get("auto_downloaded_plans", {}).get(plan_key):
                                    upload_label = f"Replace {plan['condition']} (auto-downloaded)"
                                uploaded = st.file_uploader(upload_label, type=['pdf','png','jpg'], key=existing_key)
                                # Cache uploaded file as raw bytes so it survives button-click reruns.
                                # Only update the cache when a file is actually present — never clear it.
                                if uploaded is not None:
                                    try:
                                        uploaded.seek(0)
                                        raw = uploaded.read()
                                        if raw:  # only store if non-empty
                                            st.session_state.manual_plan_uploads[plan_key] = (raw, uploaded.name)
                                    except Exception:
                                        pass
                        st.divider()
            else:
                st.caption("No action plans detected in student data.")

            # Initialise the manual plans store
            if "manual_plans_store" not in st.session_state:
                st.session_state.manual_plans_store = []  # list of {'sid': ..., 'name': ..., 'file': ...}
            if "_manual_plan_reset" not in st.session_state:
                st.session_state._manual_plan_reset = 0

            with st.expander("Add a plan manually", expanded=bool(st.session_state.manual_plans_store)):
                st.caption("Select a student, upload a file, then click **Add Plan**. Repeat for each student.")

                # Show already-added plans
                if st.session_state.manual_plans_store:
                    st.markdown("**Plans queued:**")
                    to_remove = None
                    for i, entry in enumerate(st.session_state.manual_plans_store):
                        c1, c2 = st.columns([6, 1])
                        with c1:
                            st.markdown(f"✅ **{entry['name']}** — {entry['file'].name}")
                        with c2:
                            if st.button("✕", key=f"remove_manual_plan_{i}", help="Remove this plan"):
                                to_remove = i
                    if to_remove is not None:
                        st.session_state.manual_plans_store.pop(to_remove)
                        st.rerun()
                    st.divider()

                # Use reset counter in key so widgets clear after Add Plan
                reset_key = st.session_state._manual_plan_reset
                man_sel = st.selectbox(
                    "Select student",
                    ["(Select a student)"] + sorted(list(name_to_id_map.keys())),
                    key=f"man_sel_{reset_key}"
                )
                man_file = st.file_uploader(
                    "Upload file",
                    type=['pdf', 'png', 'jpg'],
                    key=f"manual_plan_file_{reset_key}"
                )

                if st.button("Add Plan", key="add_manual_plan_btn", type="primary"):
                    if man_sel == "(Select a student)":
                        st.warning("Please select a student first.")
                    elif man_file is None:
                        st.warning("Please upload a file first.")
                    else:
                        st.session_state.manual_plans_store.append({
                            'sid': name_to_id_map[man_sel],
                            'name': man_sel,
                            'file': man_file
                        })
                        st.session_state._manual_plan_reset += 1
                        st.rerun()

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

                has_swimming   = 'swimming_csv' in st.session_state
                has_dietary    = 'dietary_csv' in st.session_state
                has_photo_perm = 'photo_perm_csv' in st.session_state

                if has_swimming or has_dietary or has_photo_perm:
                    st.markdown("---")
                    st.markdown('<div class="options-card-title">Additional data</div>', unsafe_allow_html=True)
                opt_swimming   = st.checkbox("Swimming ability",     value=True) if has_swimming   else False
                opt_dietary    = st.checkbox("Dietary requirements", value=True) if has_dietary    else False
                opt_photo_perm = st.checkbox("Photo permissions",    value=True) if has_photo_perm else False

            with col2:
                st.markdown('<div class="options-card-title">Profile sections</div>', unsafe_allow_html=True)
                opt_sec_med   = st.checkbox("Medical information",         value=True)
                opt_sec_emerg = st.checkbox("Emergency contacts",          value=True)
                opt_sec_docs  = st.checkbox("Medical contacts (doctors)",  value=True)
                opt_sec_learn = st.checkbox("Learning & support",          value=True)
                opt_sec_home  = st.checkbox("Home contacts",               value=True)

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

                # ── Gather plans ─────────────────────────────────────────────────
                plan_map = {}
                detected = st.session_state.get('detected_plans', {})
                auto_files = st.session_state.get("auto_downloaded_plan_files", {})
                manual_uploads = st.session_state.get("manual_plan_uploads", {})

                if detected:
                    for sid, plans in detected.items():
                        for idx, _ in enumerate(plans):
                            plan_key = f"{sid}_{idx}"
                            widget_key = f"plan_upload_{sid}_{idx}"

                            # Priority 1: live widget value (present on same rerun as button click)
                            live_file = st.session_state.get(widget_key)
                            if live_file is not None:
                                try:
                                    live_file.seek(0)
                                    raw = live_file.read()
                                    if raw:
                                        # Also update the persistent cache while we have it
                                        manual_uploads[plan_key] = (raw, live_file.name)
                                        buf = BytesIO(raw)
                                        buf.name = live_file.name
                                        if sid not in plan_map: plan_map[sid] = []
                                        plan_map[sid].append(buf)
                                        continue
                                except Exception:
                                    pass

                            # Priority 2: cached manual upload (raw bytes, survives reruns)
                            if plan_key in manual_uploads:
                                raw_bytes, fname = manual_uploads[plan_key]
                                if raw_bytes:
                                    buf = BytesIO(raw_bytes)
                                    buf.name = fname
                                    if sid not in plan_map: plan_map[sid] = []
                                    plan_map[sid].append(buf)
                                    continue

                            # Priority 3: auto-downloaded file
                            if plan_key in auto_files:
                                raw_bytes, fname = auto_files[plan_key]
                                if raw_bytes:
                                    buf = BytesIO(raw_bytes)
                                    buf.name = fname
                                    if sid not in plan_map: plan_map[sid] = []
                                    plan_map[sid].append(buf)

                if "medical_plan_files" in st.session_state:
                    for sid, fl in st.session_state.medical_plan_files.items():
                        if sid not in plan_map: plan_map[sid] = []
                        for f in fl:
                            plan_map[sid].append(f)

                for entry in st.session_state.get("manual_plans_store", []):
                    msid = entry['sid']
                    mf = entry['file']
                    if mf is not None:
                        try:
                            mf.seek(0)
                            raw = mf.read()
                            if raw:
                                buf = BytesIO(raw)
                                buf.name = getattr(mf, 'name', 'plan.pdf')
                                if msid not in plan_map: plan_map[msid] = []
                                plan_map[msid].append(buf)
                        except Exception:
                            pass

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

                final_photo_perm_map = st.session_state.get('photo_permissions_map', {}).copy()

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
                    "swimming": opt_swimming, "dietary": opt_dietary,
                    "photo_perm": opt_photo_perm
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
                    gender_raw = str(r.get('Gender', r.get('gender', ''))).strip()
                    gender_lower = gender_raw.lower()
                    if gender_lower == 'm': gender = 'Male'
                    elif gender_lower == 'f': gender = 'Female'
                    else:
                        # For anything other than m/f, check General notes for a "Gender:" entry
                        general_notes_text = str(r.get(COLS.get('general_notes', 'General notes'), ''))
                        gn_match = re.search(r'Gender:\s*\n?(.*?)(?:\n|$)', general_notes_text, re.IGNORECASE)
                        gn_value = gn_match.group(1).strip() if gn_match else ''
                        # The value might be blank on the same line and on the next line instead
                        if not gn_value:
                            gn_match2 = re.search(r'Gender:\s*\n([^\n]+)', general_notes_text, re.IGNORECASE)
                            gn_value = gn_match2.group(1).strip() if gn_match2 else ''
                        if gn_value and gn_value.lower() not in ('nan', ''):
                            gender = gn_value
                        elif gender_raw and gender_lower not in ('nan', ''):
                            gender = 'Other'
                        else:
                            gender = ''
                    house = str(r.get(COLS.get('house', 'House'), '')).strip()
                    tutor = parse_tutor(str(r.get(COLS.get('general_notes', 'General notes'), '')))
                    year_lvl = str(r[COLS['year']])
                    roll = str(r[COLS['rollgroup']])

                    raw_med   = str(r.get(COLS['medical_notes'], ""))
                    raw_emerg = str(r.get(COLS['emergency_notes'], ""))
                    parsed_med  = parse_medical_text(raw_med)
                    parsed_con  = parse_emergency_contacts(raw_emerg)
                    # Use Seqta PDF contacts (compulsory); fall back to CSV if missing
                    _pdf_rec = st.session_state.get('seqta_contact_matched', {}).get(sid)
                    if not _pdf_rec:
                        for _mi, _msid in st.session_state.get('seqta_contact_manual', {}).items():
                            if _msid == sid:
                                for _u in st.session_state.get('seqta_contact_unmatched', []):
                                    if _u.get('_index') == _mi:
                                        _pdf_rec = _u; break
                                break
                    parsed_home = home_contacts_from_pdf(_pdf_rec) if _pdf_rec else parse_home_contacts(r)

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
                        for f in plan_map[sid]:
                            embedded.extend(convert_file_to_images(f))
                    if sid in st.session_state.attachments:
                        for f in st.session_state.attachments[sid]: embedded.extend(convert_file_to_images(f))

                    med_l = raw_med.lower()
                    c_disp = f"{parsed_con[0]['name']} ({parsed_con[0]['phones'][0]['display']})" if parsed_con else ""

                    swim_ability    = final_swimming_map.get(sid, "Data not recorded")
                    swim_color      = get_swimming_display_color(swim_ability)
                    dietary_req     = final_dietary_map.get(sid, "No data given")
                    photo_perm_val  = final_photo_perm_map.get(sid, None)

                    profile_obj = {
                        "id": sid, "link_id": link_id, "first": fname, "last": sname,
                        "year": year_lvl, "roll": roll, "house": house, "dob": dob, "gender": gender, "tutor": tutor,
                        "swimming": swim_ability, "swim_color": swim_color,
                        "dietary": dietary_req,
                        "photo_perm": photo_perm_val,
                        "photo": img_to_base64(final_photo_map.get(sid)),
                        "sections": sections, "attachments": embedded
                    }
                    matrix_obj = {
                        "id": sid, "link_id": link_id, "name": f"{sname}, {fname}",
                        "gender": gender,
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
                    # Build no-permission list for the photo permissions page
                    no_perm_list = [
                        s for s in s_list
                        if s.get('photo_perm') in ('No', 'No Response')
                    ] if display_opts.get('photo_perm') else []
                    full_html = tpl.render(
                        title=f"{st.session_state.project_title} {title_suffix}",
                        date=datetime.now().strftime("%d %B %Y"),
                        students=s_list, matrix=m_list, medical_full=med_list,
                        no_perm_list=no_perm_list,
                        options=display_opts, mode="full",
                        student_count=len(s_list)
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

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 3 — SEQTA GROUP CREATOR
# ═══════════════════════════════════════════════════════════════════════════════
if t3 is not None:
 with t3:

    st.markdown('<div class="section-head">SEQTA Group Creator</div>', unsafe_allow_html=True)
    st.markdown(
        'Paste student email addresses and (optionally) upload a Student List CSV. '
        'The app will match emails to student ID codes — ready to paste into <a href="https://teach.friends.tas.edu.au/students/classes" target="_blank" style="color:#1a7f6e;font-weight:600">SEQTA</a>.',
        unsafe_allow_html=True
    )

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Step 1: Email addresses ───────────────────────────────────────────────
    st.markdown('''<div class="section-head">Step 1 — Student Email Addresses</div>''', unsafe_allow_html=True)
    st.markdown('<p style="font-size:0.82rem;color:#6b6f82;margin-bottom:8px;">Paste emails separated by spaces, commas, semicolons, newlines or any mix.</p>', unsafe_allow_html=True)
    email_input = st.text_area(
        "Email addresses",
        value=st.session_state.group_email_input,
        height=160,
        placeholder="e.g.\nsmith.j@school.edu.au, jones.k@school.edu.au\nbrown.t@school.edu.au",
        label_visibility="collapsed",
        key="gc_email_box"
    )
    st.session_state.group_email_input = email_input

    # ── Step 2: Student List CSV ──────────────────────────────────────────────
    st.markdown('''<div class="section-head">Step 2 — Student List CSV</div>''', unsafe_allow_html=True)
    st.markdown(f"""
    <div class="upload-card">
      <div class="upload-card-label">Student List CSV</div>
      <div class="upload-card-desc">The same student list CSV from Seqta — used to look up student codes from email addresses.
      <br><a class="seqta-link" href="{SEQTA_URL}" target="_blank" style="margin-top:6px;display:inline-flex">↗ Open in Seqta</a></div>
    </div>
    """, unsafe_allow_html=True)
    gc_csv = st.file_uploader(
        "Student List CSV for group creator",
        type="csv",
        label_visibility="collapsed",
        key="gc_csv_uploader"
    )
    # If the booklet CSV is already loaded, offer to reuse it
    if gc_csv is None and "df_final" in st.session_state:
        st.caption("💡 A student list is already loaded from the Booklet Creator — it will be used automatically if no file is uploaded here.")

    st.markdown("<br>", unsafe_allow_html=True)
    run_gc = st.button("🔍  Find Student Codes", type="primary", key="gc_run_btn")

    if run_gc:
        # ── Parse emails ─────────────────────────────────────────────────────
        raw_text = st.session_state.group_email_input.strip()
        if not raw_text:
            st.warning("Please paste at least one email address.")
        else:
            # Split on any combination of: commas, semicolons, pipes, spaces, newlines, tabs
            emails_raw = re.split(r'[\s,;|\t]+', raw_text)
            # Keep only strings that look like email addresses
            email_pattern = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
            emails = [e.strip().lower() for e in emails_raw if email_pattern.match(e.strip())]
            invalid = [e.strip() for e in emails_raw if e.strip() and not email_pattern.match(e.strip())]

            if not emails:
                st.error("No valid email addresses found. Please check your input.")
            else:
                # ── Load student data ─────────────────────────────────────────
                df_gc = None

                if gc_csv is not None:
                    try:
                        gc_csv.seek(0)
                        df_gc = pd.read_csv(gc_csv).fillna("")
                    except Exception as e:
                        st.error(f"Could not read uploaded CSV: {e}")

                elif "df_final" in st.session_state:
                    df_gc = st.session_state.df_final

                if df_gc is None:
                    st.warning("Please upload a Student List CSV (or load one via the Booklet Creator tab first).")
                else:
                    # ── Build email → student_id lookup ──────────────────────
                    # Look for an email column — try common names
                    email_col = None
                    for candidate in ["Email", "email", "Email address", "Email Address",
                                      "Student email", "Student Email", "EmailAddress"]:
                        if candidate in df_gc.columns:
                            email_col = candidate
                            break
                    # Fallback: find any column whose name contains "email" (case-insensitive)
                    if email_col is None:
                        for col in df_gc.columns:
                            if "email" in col.lower():
                                email_col = col
                                break

                    id_col = COLS.get('student_id', 'Code')
                    fname_col = COLS.get('first_name', 'First name')
                    sname_col = COLS.get('surname', 'Surname')

                    matched_ids = []
                    matched_details = []  # (email, id, name)
                    unmatched_emails = []
                    no_email_col = email_col is None

                    if not no_email_col:
                        # Build a lookup dict: normalised_email → (student_id, name)
                        lookup = {}
                        for _, row in df_gc.iterrows():
                            raw_email = str(row.get(email_col, "")).strip().lower()
                            if raw_email and raw_email != 'nan':
                                sid = str(row.get(id_col, "")).strip()
                                fname = str(row.get(fname_col, "")).strip()
                                sname = str(row.get(sname_col, "")).strip()
                                full_name = f"{fname} {sname}".strip()
                                lookup[raw_email] = (sid, full_name)

                        for email in emails:
                            if email in lookup:
                                sid, name = lookup[email]
                                matched_ids.append(sid)
                                matched_details.append((email, sid, name))
                            else:
                                unmatched_emails.append(email)
                    else:
                        unmatched_emails = emails

                    # ── Store results ─────────────────────────────────────────
                    st.session_state.group_results = {
                        "matched_ids": matched_ids,
                        "matched_details": matched_details,
                        "unmatched_emails": unmatched_emails,
                        "invalid_tokens": invalid,
                        "no_email_col": no_email_col,
                        "email_col_used": email_col,
                    }
                    st.rerun()

    # ── Display results ───────────────────────────────────────────────────────
    if st.session_state.group_results:
        res = st.session_state.group_results
        matched_ids    = res["matched_ids"]
        matched_details = res["matched_details"]
        unmatched_emails = res["unmatched_emails"]
        invalid_tokens = res["invalid_tokens"]
        no_email_col   = res["no_email_col"]

        st.markdown("---")

        if no_email_col:
            st.error(
                "⚠️ No email column was found in the student CSV. "
                "The CSV needs a column with 'email' in the name (e.g. 'Email', 'Email address'). "
                "Check your export settings in SEQTA."
            )
        else:
            result_col1, result_col2 = st.columns([3, 2])

            with result_col1:
                if matched_ids:
                    st.markdown(f'<div class="group-output-label">✅ {len(matched_ids)} student code{"s" if len(matched_ids) != 1 else ""} found — copy and paste into SEQTA</div>', unsafe_allow_html=True)
                    codes_text = "\n".join(matched_ids)
                    st.text_area(
                        "Student codes output",
                        value=codes_text,
                        height=max(120, min(400, len(matched_ids) * 26)),
                        label_visibility="collapsed",
                        key="gc_output_box"
                    )
                    st.markdown("""
                    <div class="seqta-instruction">
                      <strong>📌 Next step:</strong> In SEQTA, open your
                      <a href="https://teach.friends.tas.edu.au/students/classes" target="_blank" style="color:#7a5a00;font-weight:600">custom group editor</a>,
                      paste these codes one per line into the box on the left, then click <strong>OK</strong>.
                    </div>
                    """, unsafe_allow_html=True)
                else:
                    st.info("No student codes were matched. Check the emails and CSV below.")

            with result_col2:
                if matched_details:
                    with st.expander(f"✅ {len(matched_details)} matched", expanded=False):
                        for email, sid, name in matched_details:
                            st.markdown(f"<span style='font-size:0.8rem'><b>{sid}</b> — {name}<br><span style='color:#9295a8'>{email}</span></span>", unsafe_allow_html=True)

                if unmatched_emails:
                    with st.expander(f"❌ {len(unmatched_emails)} email{'s' if len(unmatched_emails) != 1 else ''} not matched", expanded=True):
                        st.caption("These emails were not found in the student list CSV.")
                        for em in unmatched_emails:
                            st.markdown(f"<span style='font-size:0.8rem;color:#c0392b'>{em}</span>", unsafe_allow_html=True)

                if invalid_tokens:
                    with st.expander(f"⚠️ {len(invalid_tokens)} invalid token{'s' if len(invalid_tokens) != 1 else ''} skipped"):
                        st.caption("These entries didn't look like email addresses and were ignored.")
                        for tok in invalid_tokens:
                            st.markdown(f"<span style='font-size:0.8rem;color:#9295a8'>{tok}</span>", unsafe_allow_html=True)

        if st.button("↩  Clear results", key="gc_clear_btn"):
            st.session_state.group_results = None
            st.session_state.group_email_input = ""
            st.rerun()

# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="mbc-footer">
  Medical Booklet Tools &nbsp;·&nbsp; Created by Thomas van Sant
</div>
""", unsafe_allow_html=True)